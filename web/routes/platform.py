"""平台运行态与平台资产接口。"""

from __future__ import annotations

import os

from flask import Blueprint, current_app, jsonify, render_template

from core.platform import load_experiment_registry, load_latest_run_manifest
from web.services import load_platform_ops_overview

bp = Blueprint("platform", __name__)


@bp.route("/platform/ops")
def platform_ops_page():
    return render_template("platform_ops.html")


@bp.route("/api/platform/health")
def platform_health():
    cfg = current_app.config
    base_dir = cfg["BASE_DIR"]
    latest = load_latest_run_manifest(base_dir)
    registry = load_experiment_registry(base_dir)
    output_dir = os.path.join(base_dir, "output", "platform")
    return jsonify(
        {
            "success": True,
            "platform_output_exists": os.path.exists(output_dir),
            "latest_run_status": (latest or {}).get("status", "missing"),
            "latest_run_id": (latest or {}).get("run_id", ""),
            "experiment_count": len(registry),
        }
    )


@bp.route("/api/platform/latest_run")
def platform_latest_run():
    latest = load_latest_run_manifest(current_app.config["BASE_DIR"])
    if latest is None:
        return jsonify({"success": True, "run": None})
    return jsonify({"success": True, "run": latest})


@bp.route("/api/platform/experiments")
def platform_experiments():
    items = load_experiment_registry(current_app.config["BASE_DIR"])
    return jsonify({"success": True, "items": items})


@bp.route("/api/platform/ops_overview")
def platform_ops_overview():
    try:
        payload = load_platform_ops_overview(current_app.config)
    except Exception as exc:
        current_app.config["MFTS_LOGGER"].error(f"平台运维总览加载失败: {exc}", exc_info=True)
        return jsonify({"success": False, "error": str(exc)}), 500
    return jsonify(payload)
