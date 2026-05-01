# SPDX-License-Identifier: MIT
# CI Engine - Agent Skill Auto-Detection (Enhanced)

import subprocess
import re
import json
import os
import time
import threading
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, field, asdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone

from ci_engine.core.skills import SKILL_DEFINITIONS, SKILL_CATEGORIES


SKILL_CACHE_DIR = Path(os.path.expanduser("~/.ci-engine"))
SKILL_CACHE_FILE = SKILL_CACHE_DIR / "skills_cache.json"
SKILL_CACHE_TTL_HOURS = 24


@dataclass
class DetectedSkill:
    """Represents a detected skill with version info."""

    name: str
    display_name: str
    category: str
    description: str
    version: Optional[str]
    installed: bool
    path: Optional[str]
    level: int = 1
    detected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    health_status: str = "unknown"


@dataclass
class SkillHealthCheck:
    """Result of a skill health check."""

    skill_name: str
    healthy: bool
    version: Optional[str]
    path: Optional[str]
    error: Optional[str] = None


class SkillCache:
    """Handle skill detection caching."""

    @staticmethod
    def get_cache_path() -> Path:
        SKILL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        return SKILL_CACHE_FILE

    @classmethod
    def load(cls) -> Optional[dict]:
        """Load skills from cache if valid."""
        cache_path = cls.get_cache_path()
        if not cache_path.exists():
            return None

        try:
            with open(cache_path, "r") as f:
                cache = json.load(f)

            cached_at = datetime.fromisoformat(cache.get("cached_at", "2000-01-01"))
            if datetime.now(timezone.utc) - cached_at > timedelta(hours=SKILL_CACHE_TTL_HOURS):
                return None

            return cache.get("skills", {})
        except Exception:
            return None

    @classmethod
    def save(cls, skills: dict):
        """Save skills to cache."""
        cache_path = cls.get_cache_path()
        try:
            cache = {
                "cached_at": datetime.now(timezone.utc).isoformat(),
                "skills": skills,
            }
            with open(cache_path, "w") as f:
                json.dump(cache, f)
        except Exception:
            pass

    @classmethod
    def clear(cls):
        """Clear skill cache."""
        cache_path = cls.get_cache_path()
        if cache_path.exists():
            cache_path.unlink()


class SkillDetector:
    """Auto-detect installed skills on the agent machine."""

    def __init__(self, max_workers: int = 20, use_cache: bool = True):
        self.detected_skills: dict[str, DetectedSkill] = {}
        self.max_workers = max_workers
        self.use_cache = use_cache

    def detect_all(self, force: bool = False) -> dict[str, DetectedSkill]:
        """Detect all possible skills on the system (parallel)."""
        if self.use_cache and not force:
            cached = SkillCache.load()
            if cached:
                self.detected_skills = SkillDetector._deserialize_skills(cached)
                return self.detected_skills

        self._parallel_detection()
        self._parallel_health_check()

        if self.use_cache:
            SkillCache.save(SkillDetector._serialize_skills(self.detected_skills))

        return self.detected_skills

    def _parallel_detection(self):
        """Detect skills in parallel using ThreadPoolExecutor."""
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._detect_skill_safe, name, defn): name
                for name, defn in SKILL_DEFINITIONS.items()
            }

            for future in as_completed(futures):
                try:
                    result = future.result()
                    if result and result.installed:
                        self.detected_skills[result.name] = result
                except Exception:
                    pass

    def _parallel_health_check(self):
        """Run health checks on detected skills in parallel."""
        if not self.detected_skills:
            return

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._health_check_skill, name, skill): name
                for name, skill in self.detected_skills.items()
            }

            for future in as_completed(futures):
                try:
                    health_result = future.result()
                    if health_result.name in self.detected_skills:
                        self.detected_skills[health_result.name].health_status = (
                            "healthy" if health_result.healthy else "unhealthy"
                        )
                        if not health_result.healthy:
                            self.detected_skills[health_result.name].installed = False
                except Exception:
                    pass

    def _detect_skill_safe(self, skill_name: str, skill_def) -> Optional[DetectedSkill]:
        """Safely detect a skill with fallback methods."""
        detected = self._detect_primary(skill_name, skill_def)
        if detected:
            return detected

        detected = self._detect_fallback(skill_name, skill_def)
        return detected

    def _detect_primary(self, skill_name: str, skill_def) -> Optional[DetectedSkill]:
        """Primary detection method using defined command."""
        try:
            result = subprocess.run(
                skill_def.detect_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode != 0:
                return None

            version = self._extract_version(result.stdout + result.stderr, skill_def.version_regex)
            path = self._find_executable(skill_name)

            return DetectedSkill(
                name=skill_name,
                display_name=skill_def.display_name,
                category=skill_def.category,
                description=skill_def.description,
                version=version,
                installed=True,
                path=path,
                level=skill_def.skill_level_default,
                health_status="healthy",
            )
        except Exception:
            return None

    def _detect_fallback(self, skill_name: str, skill_def) -> Optional[DetectedSkill]:
        """Fallback detection using alternative methods."""
        fallbacks = [
            f"which {skill_name}",
            f"command -v {skill_name}",
            f"type {skill_name}",
        ]

        for cmd in fallbacks:
            try:
                result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    path = result.stdout.strip()
                    version = self._extract_version_from_path(path, skill_name)
                    return DetectedSkill(
                        name=skill_name,
                        display_name=skill_def.display_name,
                        category=skill_def.category,
                        description=skill_def.description,
                        version=version,
                        installed=True,
                        path=path,
                        level=skill_def.skill_level_default,
                        health_status="healthy",
                    )
            except Exception:
                continue

        return None

    def _extract_version(self, output: str, version_regex: Optional[str]) -> Optional[str]:
        """Extract version from command output."""
        if not version_regex:
            return self._extract_version_fallback(output)

        try:
            match = re.search(version_regex, output)
            if match:
                return match.group(1) if match.groups() else match.group(0)
        except Exception:
            pass

        return self._extract_version_fallback(output)

    def _extract_version_fallback(self, output: str) -> Optional[str]:
        """Fallback version extraction - look for common patterns."""
        patterns = [
            r"(\d+\.\d+\.\d+)",
            r"(\d+\.\d+)",
            r"v(\d+\.\d+\.\d+)",
            r"version (\d+\.\d+\.\d+)",
        ]
        for pattern in patterns:
            match = re.search(pattern, output)
            if match:
                return match.group(1)
        return None

    def _extract_version_from_path(self, path: str, skill_name: str) -> Optional[str]:
        """Try to get version from the executable itself."""
        if not path or not os.path.exists(path):
            return None

        try:
            result = subprocess.run(
                f"{path} --version 2>&1 || {path} -v 2>&1 || true",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            return self._extract_version_fallback(result.stdout + result.stderr)
        except Exception:
            return None

    def _health_check_skill(self, skill_name: str, skill: DetectedSkill) -> SkillHealthCheck:
        """Run health check on a detected skill."""
        try:
            if not skill.path or not os.path.exists(skill.path):
                return SkillHealthCheck(skill_name, False, None, None, "Executable not found")

            result = subprocess.run(
                f"{skill.path} --version 2>&1 || true",
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )

            version = self._extract_version_fallback(result.stdout + result.stderr)
            return SkillHealthCheck(skill_name, True, version, skill.path)
        except Exception as e:
            return SkillHealthCheck(skill_name, False, None, None, str(e))

    def _find_executable(self, name: str) -> Optional[str]:
        """Find the path to an executable."""
        try:
            result = subprocess.run(
                f"which {name} || command -v {name} || type -p {name}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().split("\n")[0]
        except Exception:
            pass
        return None

    def get_skills_by_category(self, category: str) -> list[DetectedSkill]:
        """Get all detected skills in a category."""
        return [s for s in self.detected_skills.values() if s.category == category]

    def to_agent_skills(self) -> list[dict]:
        """Convert detected skills to agent skill format for API."""
        return [
            {
                "name": skill.name,
                "level": skill.level,
                "category": skill.category,
                "version": skill.version,
            }
            for skill in self.detected_skills.values()
            if skill.installed
        ]

    def get_summary(self) -> dict:
        """Get a summary of detected skills."""
        summary = {
            "total_detected": len(self.detected_skills),
            "total_installed": sum(1 for s in self.detected_skills.values() if s.installed),
            "by_category": {},
            "health": {
                "healthy": sum(
                    1 for s in self.detected_skills.values() if s.health_status == "healthy"
                ),
                "unhealthy": sum(
                    1 for s in self.detected_skills.values() if s.health_status == "unhealthy"
                ),
            },
        }

        for category in SKILL_CATEGORIES.keys():
            skills_in_cat = self.get_skills_by_category(category)
            installed = [s for s in skills_in_cat if s.installed]
            summary["by_category"][category] = {
                "detected": len(skills_in_cat),
                "installed": len(installed),
                "skills": [s.name for s in skills_in_cat],
            }

        return summary

    @staticmethod
    def _serialize_skills(skills: dict) -> dict:
        return {name: asdict(skill) for name, skill in skills.items()}

    @staticmethod
    def _deserialize_skills(data: dict) -> dict:
        return {name: DetectedSkill(**skill) for name, skill in data.items()}


class SkillHealthMonitor:
    """Background health monitoring for skills."""

    def __init__(self, detector: SkillDetector, interval_seconds: int = 300):
        self.detector = detector
        self.interval = interval_seconds
        self.running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        """Start background health monitoring."""
        if self.running:
            return
        self.running = True
        self._thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()

    def stop(self):
        """Stop background health monitoring."""
        self.running = False
        if self._thread:
            self._thread.join(timeout=5)

    def _monitor_loop(self):
        """Background monitoring loop."""
        while self.running:
            try:
                self.detector._parallel_health_check()
            except Exception:
                pass
            time.sleep(self.interval)


class SkillLearning:
    """Track and update skill levels based on job success."""

    LEARNING_FILE = SKILL_CACHE_DIR / "skill_learning.json"

    @classmethod
    def record_job_success(cls, skill_names: list[str]):
        """Increase skill levels on job success."""
        data = cls._load()
        for name in skill_names:
            current = data.get(name, {"level": 1, "success": 0, "failure": 0})
            current["success"] = current.get("success", 0) + 1
            if current["success"] >= 5 and current["level"] < 5:
                current["level"] = min(5, current["level"] + 1)
                current["success"] = 0
            data[name] = current
        cls._save(data)

    @classmethod
    def record_job_failure(cls, skill_names: list[str]):
        """Decrease skill levels on job failure."""
        data = cls._load()
        for name in skill_names:
            current = data.get(name, {"level": 1, "success": 0, "failure": 0})
            current["failure"] = current.get("failure", 0) + 1
            if current["failure"] >= 3 and current["level"] > 1:
                current["level"] = max(1, current["level"] - 1)
                current["failure"] = 0
            data[name] = current
        cls._save(data)

    @classmethod
    def get_learned_levels(cls) -> dict[str, int]:
        """Get learned skill levels."""
        data = cls._load()
        return {name: info["level"] for name, info in data.items()}

    @classmethod
    def _load(cls) -> dict:
        if not cls.LEARNING_FILE.exists():
            return {}
        try:
            with open(cls.LEARNING_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    @classmethod
    def _save(cls, data: dict):
        cls.LEARNING_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(cls.LEARNING_FILE, "w") as f:
                json.dump(data, f)
        except Exception:
            pass


class SkillMatcher:
    """Match jobs to agents based on skills."""

    @staticmethod
    def can_agent_run_job(agent_skills: list[dict], required_skills: list[str]) -> bool:
        """Check if agent has all required skills."""
        if not required_skills:
            return True

        agent_skill_names = {s["name"] for s in agent_skills if s.get("enabled", True)}

        for required in required_skills:
            skill_name = required.split(":")[0]
            if skill_name not in agent_skill_names:
                return False

        return True

    @staticmethod
    def get_missing_skills(agent_skills: list[dict], required_skills: list[str]) -> list[str]:
        """Get list of skills agent is missing."""
        if not required_skills:
            return []

        agent_skill_names = {s["name"] for s in agent_skills if s.get("enabled", True)}
        missing = []

        for required in required_skills:
            skill_name = required.split(":")[0]
            if skill_name not in agent_skill_names:
                missing.append(skill_name)

        return missing


class CustomSkillManager:
    """Manage user-defined custom skills."""

    CUSTOM_SKILLS_FILE = SKILL_CACHE_DIR / "custom_skills.json"

    @classmethod
    def add_custom_skill(cls, name: str, category: str, description: str, detect_command: str):
        """Add a custom skill."""
        skills = cls._load()
        skills[name] = {
            "name": name,
            "category": category,
            "description": description,
            "detect_command": detect_command,
            "custom": True,
        }
        cls._save(skills)

    @classmethod
    def remove_custom_skill(cls, name: str):
        """Remove a custom skill."""
        skills = cls._load()
        skills.pop(name, None)
        cls._save(skills)

    @classmethod
    def list_custom_skills(cls) -> dict:
        """List all custom skills."""
        return cls._load()

    @classmethod
    def _load(cls) -> dict:
        if not cls.CUSTOM_SKILLS_FILE.exists():
            return {}
        try:
            with open(cls.CUSTOM_SKILLS_FILE, "r") as f:
                return json.load(f)
        except Exception:
            return {}

    @classmethod
    def _save(cls, data: dict):
        cls.CUSTOM_SKILLS_FILE.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(cls.CUSTOM_SKILLS_FILE, "w") as f:
                json.dump(data, f)
        except Exception:
            pass


def auto_detect_skills(force: bool = False) -> dict:
    """Convenience function to auto-detect skills."""
    detector = SkillDetector(use_cache=True)
    return {
        "skills": detector.to_agent_skills(),
        "summary": detector.get_summary(),
    }


def list_all_skills(include_custom: bool = True) -> dict:
    """List all available skill definitions."""
    skills_list = []
    for name, skill in SKILL_DEFINITIONS.items():
        skills_list.append(
            {
                "name": name,
                "display_name": skill.display_name,
                "category": skill.category,
                "description": skill.description,
                "detect_command": skill.detect_command,
                "min_version": skill.min_version,
                "tags": skill.tags,
                "custom": False,
            }
        )

    if include_custom:
        custom = CustomSkillManager.list_custom_skills()
        for name, info in custom.items():
            skills_list.append(
                {
                    "name": info["name"],
                    "display_name": info["name"].title(),
                    "category": info["category"],
                    "description": info["description"],
                    "detect_command": info["detect_command"],
                    "min_version": None,
                    "tags": ["custom"],
                    "custom": True,
                }
            )

    return {
        "total": len(skills_list),
        "categories": SKILL_CATEGORIES,
        "skills": skills_list,
    }
