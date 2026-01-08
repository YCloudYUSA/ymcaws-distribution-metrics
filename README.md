# YMCA Website Services - Distribution Metrics

Code quality dashboard for the YMCA Website Services distribution ecosystem. Tracks metrics across 80+ repositories including yusaopeny, y_lb, Activity Finder, and related modules.

**Live Dashboard:** https://ycloudyusa.github.io/ymcaws-distribution-metrics/

## Metrics Tracked

- **Lines of Code (LOC)** - Production and test code over time
- **Cyclomatic Complexity (CCN)** - Decision paths per function
- **Maintainability Index (MI)** - Code maintainability score (0-100)
- **Anti-patterns** - Magic keys, deep arrays, service locators
- **API Surface Area** - Hooks, services, plugins, events
- **Commit Activity** - Features vs bugs vs maintenance
- **Per-Repository Breakdown** - Individual repo metrics

## Running Locally with DDEV

### Prerequisites

- [DDEV](https://ddev.readthedocs.io/en/stable/) installed
- Git

### Step-by-Step Guide

```bash
# 1. Clone the repository
git clone git@github.com:YCloudYUSA/ymcaws-distribution-metrics.git
cd ymcaws-distribution-metrics

# 2. Start DDEV environment
ddev start

# 3. Install PHP dependencies
ddev composer install

# 4. Run the analysis
ddev exec "cd /var/www/html && python3 scripts/analyze.py"

# 5. View results locally
ddev launch
```

The dashboard will be available at https://ymcaws-distribution-metrics.ddev.site/

### Debug Mode

For verbose output during analysis:

```bash
ddev exec "cd /var/www/html && DEBUG=1 python3 scripts/analyze.py"
```

## How It Works

1. **Repository Setup** - Clones/updates 80+ YMCA repos (GitHub + drupal.org) as bare repositories
2. **Historical Snapshots** - Analyzes semi-annual snapshots from October 2015 to present
3. **PHP Analysis** - Uses `drupalisms.php` with PHP-Parser for AST-based metrics
4. **Commit Classification** - Categorizes commits using [Conventional Commits](https://www.conventionalcommits.org/) spec
5. **Data Export** - Generates `data.json` consumed by the HTML dashboard

## Configuration

Edit `repos_config.json` to customize which repositories are analyzed:

```json
{
  "github_repos_to_analyze": [
    {"org": "YCloudYUSA", "repo": "yusaopeny", "ymca": true}
  ],
  "drupal_org_ymca_modules": [
    "openy_activity_finder",
    "lb_accordion"
  ]
}
```

## Automated Updates

GitHub Actions runs weekly (Monday 2am UTC) to refresh metrics and deploy to GitHub Pages.

## Project Structure

```
.
├── scripts/
│   ├── analyze.py       # Main Python orchestrator
│   └── drupalisms.php   # PHP AST analyzer
├── repos_config.json    # Repository configuration
├── data.json           # Generated metrics data
├── index.html          # Dashboard UI
└── .github/workflows/  # CI/CD automation
```

## License

MIT
