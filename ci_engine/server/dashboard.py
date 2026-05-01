# SPDX-License-Identifier: MIT
# CI Engine - Web Dashboard (HTML)

from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from ci_engine.server.db import get_db
from ci_engine.server.models import Build, Agent

router = APIRouter()


DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <title>CI Engine</title>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #f5f5f5; }
        .header { background: #1a1a2e; color: white; padding: 20px; }
        .header h1 { font-size: 24px; }
        .status-bar { display: flex; gap: 20px; margin-top: 15px; }
        .status-item { text-align: center; }
        .status-item .value { font-size: 28px; font-weight: bold; }
        .status-item .label { font-size: 12px; opacity: 0.8; }
        .container { max-width: 1200px; margin: 0 auto; padding: 20px; }
        .section { background: white; border-radius: 8px; padding: 20px; margin-bottom: 20px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .section h2 { font-size: 18px; margin-bottom: 15px; color: #333; }
        table { width: 100%; border-collapse: collapse; }
        th, td { padding: 12px; text-align: left; border-bottom: 1px solid #eee; }
        th { font-weight: 600; color: #666; font-size: 12px; text-transform: uppercase; }
        .status { display: inline-block; padding: 4px 8px; border-radius: 4px; font-size: 12px; font-weight: 500; }
        .status.pending { background: #fef3c7; color: #92400e; }
        .status.running { background: #dbeafe; color: #1e40af; }
        .status.passed { background: #d1fae5; color: #065f46; }
        .status.failed { background: #fee2e2; color: #991b1b; }
        .status.idle { background: #d1fae5; color: #065f46; }
        .status.busy { background: #dbeafe; color: #1e40af; }
        .btn { display: inline-block; padding: 8px 16px; background: #4f46e5; color: white; text-decoration: none; border-radius: 4px; font-size: 14px; }
        .btn:hover { background: #4338ca; }
        .refresh { text-align: right; margin-bottom: 10px; }
    </style>
</head>
<body>
    <div class="header">
        <h1>CI Engine</h1>
        <div class="status-bar">
            <div class="status-item">
                <div class="value">{{ stats.builds_24h }}</div>
                <div class="label">builds (24h)</div>
            </div>
            <div class="status-item">
                <div class="value">{{ stats.total_builds }}</div>
                <div class="label">total builds</div>
            </div>
            <div class="status-item">
                <div class="value">{{ stats.active_pipelines }}</div>
                <div class="label">active pipelines</div>
            </div>
            <div class="status-item">
                <div class="value">{{ agents|length }}</div>
                <div class="label">agents</div>
            </div>
        </div>
    </div>
    <div class="container">
        <div class="section">
            <div class="refresh">
                <a href="/" class="btn">Refresh</a>
            </div>
            <h2>Recent Builds</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Branch</th>
                        <th>Status</th>
                        <th>Created</th>
                    </tr>
                </thead>
                <tbody>
                    {% for build in builds %}
                    <tr>
                        <td>#{{ build.id }}</td>
                        <td>{{ build.branch }}</td>
                        <td><span class="status {{ build.status }}">{{ build.status }}</span></td>
                        <td>{{ build.created_at[:19] }}</td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
        <div class="section">
            <h2>Agents</h2>
            <table>
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Name</th>
                        <th>Hostname</th>
                        <th>Status</th>
                    </tr>
                </thead>
                <tbody>
                    {% for agent in agents %}
                    <tr>
                        <td>#{{ agent.id }}</td>
                        <td>{{ agent.name }}</td>
                        <td>{{ agent.hostname }}</td>
                        <td><span class="status {{ agent.status }}">{{ agent.status }}</span></td>
                    </tr>
                    {% endfor %}
                </tbody>
            </table>
        </div>
    </div>
</body>
</html>
"""


@router.get("/", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):
    """Render the main dashboard."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    day_ago = now - timedelta(days=1)

    builds = db.query(Build).order_by(Build.created_at.desc()).limit(20).all()
    agents = db.query(Agent).all()

    stats = {
        "builds_24h": db.query(Build).filter(Build.created_at >= day_ago).count(),
        "total_builds": db.query(Build).count(),
        "active_pipelines": db.query(Build).filter(Build.status == "running").count(),
    }

    from jinja2 import Template

    template = Template(DASHBOARD_HTML)
    return template.render(builds=builds, agents=agents, stats=stats)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard_alias(db: Session = Depends(get_db)):
    return dashboard(db)
