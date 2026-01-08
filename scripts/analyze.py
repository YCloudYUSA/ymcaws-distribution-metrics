#!/usr/bin/env python3
"""
YMCA Website Services Distribution - Metrics Collection Script

Analyzes YMCA WS distribution across historical snapshots, collecting metrics like
LOC, CCN, MI, anti-patterns, and API surface area. Uses drupalisms.php for all analysis.

Supports multi-repo analysis from repos_config.json.
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional


# Configuration
DISTRIBUTION_START_DATE = datetime(2015, 10, 1)  # yusaopeny first commit


class Colors:
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    RED = "\033[0;31m"
    NC = "\033[0m"


def log_info(message: str):
    print(f"{Colors.GREEN}[INFO]{Colors.NC} {message}", flush=True)


def log_warn(message: str):
    print(f"{Colors.YELLOW}[WARN]{Colors.NC} {message}", flush=True)


def log_error(message: str):
    print(f"{Colors.RED}[ERROR]{Colors.NC} {message}", flush=True)


def run_command(cmd: list[str], cwd: Optional[str] = None, capture: bool = True) -> tuple[int, str, str]:
    """Run a shell command and return (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=capture,
            text=True,
            timeout=600  # 10 minute timeout
        )
        return result.returncode, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return 1, "", "Command timed out"
    except Exception as e:
        return 1, "", str(e)


def load_config(project_dir: Path) -> dict:
    """Load repos_config.json."""
    config_file = project_dir / "repos_config.json"
    if not config_file.exists():
        log_error(f"Config file not found: {config_file}")
        sys.exit(1)
    with open(config_file) as f:
        return json.load(f)


def get_repo_url(org: str, repo: str) -> str:
    """Get GitHub repo URL."""
    return f"https://github.com/{org}/{repo}.git"


def setup_repo(repos_dir: Path, org: str, repo: str) -> Optional[Path]:
    """Clone or update a repository."""
    repo_dir = repos_dir / f"{org}_{repo}"
    repo_url = get_repo_url(org, repo)

    if repo_dir.exists():
        log_info(f"Updating {org}/{repo}...")
        code, _, err = run_command(["git", "fetch", "origin", "--tags"], cwd=str(repo_dir))
        if code != 0:
            log_warn(f"Failed to fetch {org}/{repo}: {err}")
            return None
        code, head_ref, _ = run_command(["git", "symbolic-ref", "HEAD"], cwd=str(repo_dir))
        if code == 0:
            run_command(["git", "update-ref", head_ref.strip(), "FETCH_HEAD"], cwd=str(repo_dir))
    else:
        log_info(f"Cloning {org}/{repo}...")
        code, _, err = run_command(["git", "clone", "--bare", repo_url, str(repo_dir)])
        if code != 0:
            log_warn(f"Failed to clone {org}/{repo}: {err}")
            return None
    return repo_dir


def get_commit_for_date(repo_dir: Path, target_date: str) -> Optional[str]:
    """Get the commit hash closest to the target date."""
    code, stdout, _ = run_command(
        ["git", "rev-list", "-1", f"--before={target_date}T23:59:59", "HEAD"],
        cwd=str(repo_dir)
    )
    if code == 0 and stdout.strip():
        return stdout.strip()
    return None


def get_commits_per_year(repo_dirs: list[Path]) -> list[dict]:
    """Count commits per year from git history across all repos."""
    year_counts = {}

    for repo_dir in repo_dirs:
        code, stdout, _ = run_command(
            ["git", "log", "--pretty=format:%ad", "--date=format:%Y"],
            cwd=str(repo_dir)
        )
        if code != 0 or not stdout.strip():
            continue

        for line in stdout.strip().split('\n'):
            year = line.strip()
            if year:
                year_counts[year] = year_counts.get(year, 0) + 1

    result = [{"year": int(year), "commits": count} for year, count in year_counts.items()]
    result.sort(key=lambda x: x["year"])
    return result


def classify_commit(subject: str) -> str:
    """Classify a commit by its message prefix."""
    subject = subject.strip().lower()
    if subject.startswith(("fix:", "bug:", "bugfix:")):
        return "Bug"
    elif subject.startswith(("feat:", "feature:")):
        return "Feature"
    elif subject.startswith(("task:", "docs:", "ci:", "test:", "perf:", "chore:", "refactor:")):
        return "Maintenance"
    # Check for issue patterns like "Issue #123" or merge commits
    if "merge" in subject:
        return "Maintenance"
    return "Unknown"


def get_commits_per_month(repo_dirs: list[Path]) -> list[dict]:
    """Count commits per month from git history across all repos."""
    month_counts = {}

    for repo_dir in repo_dirs:
        code, stdout, _ = run_command(
            ["git", "log", "--pretty=format:%ad|%s", "--date=format:%Y-%m"],
            cwd=str(repo_dir)
        )
        if code != 0 or not stdout.strip():
            continue

        for line in stdout.strip().split('\n'):
            if '|' not in line:
                continue
            date, subject = line.split('|', 1)
            date = date.strip()

            if date not in month_counts:
                month_counts[date] = {"total": 0, "features": 0, "bugs": 0, "maintenance": 0, "unknown": 0}

            month_counts[date]["total"] += 1
            commit_type = classify_commit(subject)
            if commit_type == "Bug":
                month_counts[date]["bugs"] += 1
            elif commit_type == "Feature":
                month_counts[date]["features"] += 1
            elif commit_type == "Maintenance":
                month_counts[date]["maintenance"] += 1
            else:
                month_counts[date]["unknown"] += 1

    result = [{"date": date, **counts} for date, counts in month_counts.items()]
    result.sort(key=lambda x: x["date"])
    return result


def export_version(repo_dir: Path, commit: str, work_dir: Path, subdir: str = "") -> bool:
    """Export a specific version of a repo to work directory."""
    target_dir = work_dir / subdir if subdir else work_dir
    if target_dir.exists():
        shutil.rmtree(target_dir)
    target_dir.mkdir(parents=True)

    try:
        git_proc = subprocess.Popen(
            ["git", "archive", commit],
            cwd=str(repo_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        tar_proc = subprocess.Popen(
            ["tar", "-x", "-C", str(target_dir)],
            stdin=git_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        git_proc.stdout.close()
        tar_proc.communicate(timeout=300)
        git_proc.wait()
        return tar_proc.returncode == 0 and git_proc.returncode == 0
    except Exception as e:
        log_warn(f"Failed to archive {commit[:8]}: {e}")
        return False


def get_recent_commits(repo_dirs: list[Path], days: int = 365) -> list[dict]:
    """Get recent commits from all repos."""
    commits = []

    for repo_dir in repo_dirs:
        repo_name = repo_dir.name
        code, stdout, _ = run_command(
            ["git", "log", f"--since={days} days ago", "--pretty=format:COMMIT:%H:%cs:%s", "--shortstat"],
            cwd=str(repo_dir)
        )
        if code != 0:
            continue

        current_hash = None
        current_msg = None
        current_date = None

        for line in stdout.split('\n'):
            line = line.strip()
            if line.startswith('COMMIT:'):
                parts = line.split(':', 3)
                if len(parts) >= 4:
                    current_hash = parts[1]
                    current_date = parts[2]
                    current_msg = parts[3][:80]
            elif 'changed' in line and current_hash:
                insertions = deletions = 0
                match_ins = re.search(r'(\d+) insertion', line)
                match_del = re.search(r'(\d+) deletion', line)
                if match_ins:
                    insertions = int(match_ins.group(1))
                if match_del:
                    deletions = int(match_del.group(1))
                total = insertions + deletions
                try:
                    dt = datetime.strptime(current_date, "%Y-%m-%d")
                    formatted_date = dt.strftime("%b %d, %Y")
                except ValueError:
                    formatted_date = current_date
                commits.append({
                    'hash': current_hash,
                    'message': current_msg,
                    'date': formatted_date,
                    'sort_date': current_date,
                    'lines': total,
                    'type': classify_commit(current_msg),
                    'repo': repo_name
                })
                current_hash = None

    commits = sorted(commits, key=lambda x: x['sort_date'], reverse=True)
    for c in commits:
        del c['sort_date']
    return commits[:200]  # Limit to 200 most recent


def analyze_directory(work_dir: Path, php_script: Path) -> Optional[dict]:
    """Analyze a directory using drupalisms.php."""
    # Find PHP files to analyze
    php_files = list(work_dir.rglob("*.php")) + list(work_dir.rglob("*.module")) + list(work_dir.rglob("*.inc"))
    if not php_files:
        return None

    try:
        result = subprocess.run(
            ["php", "-d", "memory_limit=2G", str(php_script), str(work_dir)],
            capture_output=True,
            text=True,
            timeout=600
        )
        if result.returncode != 0:
            return None

        return json.loads(result.stdout)
    except Exception:
        return None


def analyze_version(repo_dirs: list[Path], year_month: str, output_dir: Path,
                    current: int = 0, total: int = 0) -> Optional[dict]:
    """Analyze a specific point in time across all repos."""
    work_dir = output_dir / "work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    progress = f" [{current}/{total}]" if total else ""
    log_info(f"Analyzing {year_month}{progress}")

    target_date = f"{year_month}-15"  # Mid-month
    exported_any = False

    for repo_dir in repo_dirs:
        commit = get_commit_for_date(repo_dir, target_date)
        if commit:
            repo_name = repo_dir.name
            if export_version(repo_dir, commit, work_dir, repo_name):
                exported_any = True

    if not exported_any:
        log_warn(f"No repos exported for {year_month}")
        return None

    scripts_dir = Path(__file__).parent
    php_script = scripts_dir / "drupalisms.php"

    data = analyze_directory(work_dir, php_script)
    if not data:
        log_warn(f"Analysis failed for {year_month}")
        return None

    return {
        "date": year_month,
        "commit": "multi",
        "production": data.get("production", {}),
        "testLoc": data.get("testLoc", 0),
        "surfaceArea": data.get("surfaceArea", {}),
        "surfaceAreaLists": data.get("surfaceAreaLists", {}),
        "antipatterns": data.get("antipatterns", {}),
        "hotspots": data.get("hotspots", []),
    }


def main():
    project_dir = Path(__file__).parent.parent.resolve()
    repos_dir = project_dir / "repos"
    output_dir = project_dir / "output"
    data_file = project_dir / "data.json"

    log_info("Starting YMCA Website Services Distribution metrics collection")

    # Load configuration
    config = load_config(project_dir)

    # Create directories
    repos_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    # Get primary repos to analyze
    github_repos = config.get("github_repos_to_analyze", [])
    primary_repos = [r for r in github_repos if r.get("primary", False) and r.get("ymca", True)]

    log_info(f"Found {len(primary_repos)} primary repos to analyze")

    # Clone/update repos
    repo_dirs = []
    for repo_config in primary_repos:
        org = repo_config["org"]
        repo = repo_config["repo"]
        repo_dir = setup_repo(repos_dir, org, repo)
        if repo_dir:
            repo_dirs.append(repo_dir)

    if not repo_dirs:
        log_error("No repos available for analysis")
        sys.exit(1)

    log_info(f"Successfully set up {len(repo_dirs)} repos")

    # Build list of semi-annual snapshots
    today = datetime.now()
    target = DISTRIBUTION_START_DATE.replace(day=1)
    snapshot_dates = []
    while target <= today:
        snapshot_dates.append(target)
        new_month = target.month + 6
        if new_month > 12:
            target = target.replace(year=target.year + 1, month=new_month - 12)
        else:
            target = target.replace(month=new_month)

    total = len(snapshot_dates)
    log_info(f"Analyzing {total} semi-annual snapshots")

    snapshots = []
    for i, target in enumerate(snapshot_dates, 1):
        year_month = target.strftime("%Y-%m")
        result = analyze_version(repo_dirs, year_month, output_dir, i, total)
        if result:
            snapshots.append(result)

    # Analyze current HEAD
    log_info("Analyzing current HEAD...")
    current_date = datetime.now().strftime("%Y-%m")
    if not snapshots or snapshots[-1]["date"] != current_date:
        result = analyze_version(repo_dirs, current_date, output_dir)
        if result:
            snapshots.append(result)

    # Cleanup work directory
    work_dir = output_dir / "work"
    if work_dir.exists():
        shutil.rmtree(work_dir)

    # Get commit statistics
    commits = get_recent_commits(repo_dirs, days=365)
    log_info(f"Found {len(commits)} recent commits")

    commitsPerYear = get_commits_per_year(repo_dirs)
    log_info(f"Counted commits across {len(commitsPerYear)} years")

    commitsMonthly = get_commits_per_month(repo_dirs)
    log_info(f"Counted commits across {len(commitsMonthly)} months")

    # Build final data structure
    data = {
        "generated": datetime.now().isoformat(),
        "distribution": "YMCA Website Services",
        "repos_analyzed": [r.name for r in repo_dirs],
        "commitsMonthly": commitsMonthly,
        "snapshots": snapshots,
        "commits": commits,
        "commitsPerYear": commitsPerYear,
    }

    # Save results
    with open(data_file, "w") as f:
        json.dump(data, f, indent=2)

    log_info(f"Analysis complete! Processed {len(snapshots)} snapshots.")
    log_info(f"Data saved to: {data_file}")


if __name__ == "__main__":
    main()
