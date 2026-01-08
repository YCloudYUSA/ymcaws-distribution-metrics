#!/usr/bin/env python3
"""
YMCA Website Services Distribution - Metrics Collection Script

Analyzes YMCA WS distribution across historical snapshots, collecting metrics like
LOC, CCN, MI, anti-patterns, and API surface area. Uses drupalisms.php for all analysis.

Supports multi-repo analysis from repos_config.json.
"""

import json
import os
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


def log_debug(message: str):
    if os.environ.get("DEBUG"):
        print(f"[DEBUG] {message}", flush=True)


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


def get_drupal_org_repo_url(module: str) -> str:
    """Get drupal.org GitLab repo URL."""
    return f"https://git.drupalcode.org/project/{module}.git"


def setup_drupal_org_repo(repos_dir: Path, module: str) -> Optional[Path]:
    """Clone or update a drupal.org repository."""
    repo_dir = repos_dir / f"drupal_{module}"
    repo_url = get_drupal_org_repo_url(module)

    if repo_dir.exists():
        log_info(f"Updating drupal.org/{module}...")
        code, _, err = run_command(["git", "fetch", "origin", "--tags"], cwd=str(repo_dir))
        if code != 0:
            log_warn(f"Failed to fetch drupal.org/{module}: {err}")
            return None
        code, head_ref, _ = run_command(["git", "symbolic-ref", "HEAD"], cwd=str(repo_dir))
        if code == 0:
            run_command(["git", "update-ref", head_ref.strip(), "FETCH_HEAD"], cwd=str(repo_dir))
    else:
        log_info(f"Cloning drupal.org/{module}...")
        code, _, err = run_command(["git", "clone", "--bare", repo_url, str(repo_dir)])
        if code != 0:
            log_warn(f"Failed to clone drupal.org/{module}: {err}")
            return None
    return repo_dir


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
    """Classify a commit by its message using Conventional Commits specification.

    Format: <type>[optional scope][!]: <description>
    See: https://www.conventionalcommits.org/en/v1.0.0/
    """
    subject = subject.strip().lower()

    # Conventional commits pattern: type(optional-scope)!: description
    # Types that indicate bugs
    bug_pattern = r'^(fix|bugfix|bug|hotfix)(\([^)]+\))?!?:'
    if re.match(bug_pattern, subject):
        return "Bug"

    # Types that indicate features
    feature_pattern = r'^(feat|feature)(\([^)]+\))?!?:'
    if re.match(feature_pattern, subject):
        return "Feature"

    # Types that indicate maintenance/tasks
    maintenance_pattern = r'^(build|chore|ci|docs|style|refactor|perf|test|task|revert)(\([^)]+\))?!?:'
    if re.match(maintenance_pattern, subject):
        return "Maintenance"

    # Drupal-style issue references: "Issue #1234567"
    if re.match(r'^issue\s*#?\d+', subject):
        return "Maintenance"

    # Merge commits
    if subject.startswith("merge"):
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
        log_debug(f"No PHP files found in {work_dir}")
        return None

    log_debug(f"Found {len(php_files)} PHP files to analyze")

    try:
        result = subprocess.run(
            ["php", "-d", "memory_limit=2G", str(php_script), str(work_dir)],
            capture_output=True,
            text=True,
            timeout=600
        )
        if result.returncode != 0:
            log_debug(f"PHP analysis failed: {result.stderr[:500]}")
            return None

        if not result.stdout.strip():
            log_debug("PHP analysis returned empty output")
            return None

        data = json.loads(result.stdout)
        log_debug(f"PHP analysis returned data with keys: {list(data.keys())}")
        return data
    except json.JSONDecodeError as e:
        log_debug(f"JSON decode error: {e}")
        return None
    except Exception as e:
        log_debug(f"Exception during analysis: {e}")
        return None


def analyze_version(repo_dirs: list[Path], year_month: str, output_dir: Path,
                    php_script: Path, current: int = 0, total: int = 0,
                    collect_per_repo: bool = False) -> Optional[dict]:
    """Analyze a specific point in time across all repos."""
    work_dir = output_dir / "work"
    if work_dir.exists():
        shutil.rmtree(work_dir)
    work_dir.mkdir(parents=True)

    progress = f" [{current}/{total}]" if total else ""
    log_info(f"Analyzing {year_month}{progress}")

    target_date = f"{year_month}-15"  # Mid-month
    exported_any = False
    exported_repos = []

    for repo_dir in repo_dirs:
        commit = get_commit_for_date(repo_dir, target_date)
        if commit:
            repo_name = repo_dir.name
            if export_version(repo_dir, commit, work_dir, repo_name):
                exported_any = True
                exported_repos.append(repo_name)

    if not exported_any:
        log_warn(f"No repos exported for {year_month}")
        return None

    log_debug(f"Exported {len(exported_repos)} repos for {year_month}")

    data = analyze_directory(work_dir, php_script)
    if not data:
        log_warn(f"Analysis returned no data for {year_month}")
        return None

    result = {
        "date": year_month,
        "commit": "multi",
        "production": data.get("production", {}),
        "testLoc": data.get("testLoc", 0),
        "surfaceArea": data.get("surfaceArea", {}),
        "surfaceAreaLists": data.get("surfaceAreaLists", {}),
        "antipatterns": data.get("antipatterns", {}),
        "hotspots": data.get("hotspots", []),
    }

    # Collect per-repo stats for current snapshot
    if collect_per_repo:
        per_repo = []
        for repo_name in exported_repos:
            repo_work_dir = work_dir / repo_name
            if repo_work_dir.exists():
                repo_data = analyze_directory(repo_work_dir, php_script)
                if repo_data:
                    # Clean up repo name for display
                    display_name = repo_name
                    for prefix in ["YCloudYUSA_", "open-y-subprojects_", "drupal_"]:
                        if display_name.startswith(prefix):
                            display_name = display_name[len(prefix):]
                            break
                    per_repo.append({
                        "name": display_name,
                        "loc": repo_data.get("production", {}).get("loc", 0),
                        "ccn": repo_data.get("production", {}).get("ccn", {}).get("avg", 0),
                        "mi": repo_data.get("production", {}).get("mi", {}).get("avg", 0),
                        "antipatterns": sum(repo_data.get("antipatterns", {}).values()),
                    })
        # Sort by LOC descending
        per_repo.sort(key=lambda x: x["loc"], reverse=True)
        result["perRepo"] = per_repo
        log_info(f"Collected stats for {len(per_repo)} individual repos")

    return result


def find_project_dir() -> Path:
    """Find the project directory regardless of where script is run from."""
    # Try relative to script location first
    script_dir = Path(__file__).parent.resolve()
    project_dir = script_dir.parent

    if (project_dir / "repos_config.json").exists():
        return project_dir

    # If running from DDEV, check common mount points
    for possible_path in [Path("/var/www/html"), Path.cwd()]:
        if (possible_path / "repos_config.json").exists():
            return possible_path

    log_error("Could not find project directory with repos_config.json")
    sys.exit(1)


def main():
    project_dir = find_project_dir()
    log_info(f"Project directory: {project_dir}")

    scripts_dir = project_dir / "scripts"
    php_script = scripts_dir / "drupalisms.php"

    if not php_script.exists():
        log_error(f"PHP script not found: {php_script}")
        sys.exit(1)

    repos_dir = project_dir / "repos"
    output_dir = project_dir / "output"
    data_file = project_dir / "data.json"

    log_info("Starting YMCA Website Services Distribution metrics collection")

    # Load configuration
    config = load_config(project_dir)

    # Create directories
    repos_dir.mkdir(exist_ok=True)
    output_dir.mkdir(exist_ok=True)

    # Get ALL YMCA repos to analyze
    github_repos = config.get("github_repos_to_analyze", [])
    ymca_github_repos = [r for r in github_repos if r.get("ymca", True)]
    drupal_org_modules = config.get("drupal_org_ymca_modules", [])

    total_repos = len(ymca_github_repos) + len(drupal_org_modules)
    log_info(f"Found {total_repos} YMCA repos to analyze ({len(ymca_github_repos)} GitHub + {len(drupal_org_modules)} drupal.org)")

    # Clone/update GitHub repos
    repo_dirs = []
    for repo_config in ymca_github_repos:
        org = repo_config["org"]
        repo = repo_config["repo"]
        repo_dir = setup_repo(repos_dir, org, repo)
        if repo_dir:
            repo_dirs.append(repo_dir)

    # Clone/update drupal.org repos
    for module in drupal_org_modules:
        repo_dir = setup_drupal_org_repo(repos_dir, module)
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
        result = analyze_version(repo_dirs, year_month, output_dir, php_script, i, total)
        if result:
            snapshots.append(result)
            log_debug(f"Snapshot {year_month} added, total snapshots: {len(snapshots)}")

    # Analyze current HEAD with per-repo stats
    log_info("Analyzing current HEAD with per-repo breakdown...")
    current_date = datetime.now().strftime("%Y-%m")
    if not snapshots or snapshots[-1]["date"] != current_date:
        result = analyze_version(repo_dirs, current_date, output_dir, php_script,
                                collect_per_repo=True)
        if result:
            snapshots.append(result)

    # Cleanup work directory
    work_dir = output_dir / "work"
    if work_dir.exists():
        shutil.rmtree(work_dir)

    log_info(f"Collected {len(snapshots)} snapshots with data")

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

    # Verify data before saving
    if not snapshots:
        log_error("No snapshots collected! Check if PHP analysis is working.")
        log_info("Saving partial data anyway...")

    # Save results
    try:
        log_info(f"Saving data to {data_file}...")
        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        log_info(f"JSON serialization successful, {len(json_str)} characters")

        with open(data_file, "w", encoding="utf-8") as f:
            f.write(json_str)

        # Verify the file was written
        actual_size = data_file.stat().st_size
        log_info(f"Data saved to: {data_file} ({actual_size} bytes)")

        if actual_size == 0:
            log_error("File was written but is empty!")
        elif actual_size < 1000:
            log_warn(f"File seems small. Content preview: {json_str[:500]}")

    except Exception as e:
        log_error(f"Failed to save data: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    log_info(f"Analysis complete! Processed {len(snapshots)} snapshots.")


if __name__ == "__main__":
    main()
