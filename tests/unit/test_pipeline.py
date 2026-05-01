# SPDX-License-Identifier: MIT
# CI Engine - Unit tests for pipeline module

from ci_engine.core.pipeline import parse_pipeline, parse_pipeline_file


class TestPipelineParsing:
    """Tests for pipeline parsing functionality."""

    def test_parse_simple_steps(self):
        """Test parsing simple pipeline with steps."""
        pipeline = """
steps:
  - label: "Build"
    command: "make build"
  - label: "Test"
    command: "make test"
"""
        result = parse_pipeline(pipeline)
        assert len(result) == 2
        assert result[0]["label"] == "Build"
        assert result[0]["command"] == "make build"
        assert result[1]["label"] == "Test"
        assert result[1]["command"] == "make test"

    def test_parse_empty_pipeline(self):
        """Test parsing empty pipeline returns empty list."""
        result = parse_pipeline("")
        assert result == []

    def test_parse_invalid_yaml(self):
        """Test parsing invalid YAML returns empty list."""
        result = parse_pipeline("invalid: yaml: content:")
        assert result == []

    def test_parse_pipeline_with_env(self):
        """Test parsing pipeline with environment variables."""
        pipeline = """
steps:
  - label: "Build"
    command: "make build"
    env:
      - DEBUG=true
      - VERSION=1.0
"""
        result = parse_pipeline(pipeline)
        assert len(result) == 1
        assert result[0]["env"] == {"DEBUG": "true", "VERSION": "1.0"}

    def test_parse_pipeline_with_skip(self):
        """Test parsing pipeline with skip flag."""
        pipeline = """
steps:
  - label: "Deploy"
    command: "make deploy"
    skip: true
"""
        result = parse_pipeline(pipeline)
        assert result[0]["skip"] is True

    def test_parse_pipeline_with_plugins(self):
        """Test parsing pipeline with plugins."""
        pipeline = """
steps:
  - label: "Test"
    command: "pytest"
    plugins:
      - docker-compose#v3.7.0
"""
        result = parse_pipeline(pipeline)
        assert result[0]["plugins"] == ["docker-compose#v3.7.0"]

    def test_parse_pipeline_file_not_found(self):
        """Test parsing non-existent file returns empty list."""
        result = parse_pipeline_file("/nonexistent/pipeline.yml")
        assert result == []

    def test_parse_soft_fail_on_error(self):
        """Test parsing handles errors gracefully."""
        result = parse_pipeline("")
        assert result == []
