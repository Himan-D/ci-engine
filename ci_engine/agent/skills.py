# SPDX-License-Identifier: MIT
# CI Engine - Agent Skill Auto-Detection

import subprocess
import re
import json
import os
from typing import Optional
from dataclasses import dataclass

from ci_engine.core.skills import SKILL_DEFINITIONS, get_skill_by_name, SKILL_CATEGORIES


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


class SkillDetector:
    """Auto-detect installed skills on the agent machine."""

    def __init__(self):
        self.detected_skills: dict[str, DetectedSkill] = {}

    def detect_all(self) -> dict[str, DetectedSkill]:
        """Detect all possible skills on the system."""
        for skill_name, skill_def in SKILL_DEFINITIONS.items():
            detected = self._detect_skill(skill_name, skill_def)
            if detected:
                self.detected_skills[skill_name] = detected

        return self.detected_skills

    def detect_skill(self, skill_name: str) -> Optional[DetectedSkill]:
        """Detect a specific skill."""
        skill_def = get_skill_by_name(skill_name)
        if not skill_def:
            return None
        return self._detect_skill(skill_name, skill_def)

    def _detect_skill(self, skill_name: str, skill_def) -> Optional[DetectedSkill]:
        """Detect a skill using its detection command."""
        try:
            result = subprocess.run(
                skill_def.detect_command,
                shell=True,
                capture_output=True,
                text=True,
                timeout=10,
            )

            version = self._extract_version(result.stdout + result.stderr, skill_def.version_regex)

            path = self._find_executable(skill_name)

            return DetectedSkill(
                name=skill_name,
                display_name=skill_def.display_name,
                category=skill_def.category,
                description=skill_def.description,
                version=version,
                installed=result.returncode == 0,
                path=path,
                level=skill_def.skill_level_default,
            )
        except subprocess.TimeoutExpired:
            return None
        except Exception:
            return None

    def _extract_version(self, output: str, version_regex: Optional[str]) -> Optional[str]:
        """Extract version from command output."""
        if not version_regex:
            return None

        try:
            match = re.search(version_regex, output)
            if match:
                return match.group(1) if match.groups() else match.group(0)
        except Exception:
            pass

        return None

    def _find_executable(self, name: str) -> Optional[str]:
        """Find the path to an executable."""
        try:
            result = subprocess.run(
                f"which {name}",
                shell=True,
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
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


def auto_detect_skills() -> dict:
    """Convenience function to auto-detect skills."""
    detector = SkillDetector()
    skills = detector.detect_all()
    return {
        "skills": detector.to_agent_skills(),
        "summary": detector.get_summary(),
    }


def list_all_skills() -> dict:
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
            }
        )

    return {
        "total": len(skills_list),
        "categories": SKILL_CATEGORIES,
        "skills": skills_list,
    }
