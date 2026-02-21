from __future__ import annotations

from sag.schema import ArgType, SchemaRegistry, VerbSchema


class SoftwareDevProfile:
    """Pre-built schema profile for common software development verbs."""

    _VERBS = [
        "build", "test", "deploy", "rollback", "review", "merge",
        "lint", "scan", "release", "provision", "monitor", "migrate",
    ]

    @staticmethod
    def create_registry() -> SchemaRegistry:
        """Return a SchemaRegistry pre-populated with software development verb schemas."""
        registry = SchemaRegistry()

        registry.register(
            VerbSchema.Builder("build")
            .add_positional_arg("target", ArgType.STRING, True, "Build target")
            .add_named_arg("config", ArgType.STRING, False, "Build configuration")
            .add_named_arg("clean", ArgType.BOOLEAN, False, "Clean before building")
            .build()
        )

        registry.register(
            VerbSchema.Builder("test")
            .add_positional_arg("suite", ArgType.STRING, True, "Test suite to run")
            .add_named_arg("coverage", ArgType.BOOLEAN, False, "Enable coverage reporting")
            .add_named_arg("timeout", ArgType.INTEGER, False, "Timeout in seconds",
                           min_value=1, max_value=3600)
            .add_named_arg("parallel", ArgType.BOOLEAN, False, "Run tests in parallel")
            .build()
        )

        registry.register(
            VerbSchema.Builder("deploy")
            .add_positional_arg("app", ArgType.STRING, True, "Application to deploy")
            .add_named_arg("version", ArgType.INTEGER, False, "Version number")
            .add_named_arg("env", ArgType.STRING, False, "Target environment",
                           allowed_values=["dev", "staging", "production"])
            .add_named_arg("replicas", ArgType.INTEGER, False, "Number of replicas",
                           min_value=1, max_value=100)
            .build()
        )

        registry.register(
            VerbSchema.Builder("rollback")
            .add_positional_arg("app", ArgType.STRING, True, "Application to rollback")
            .add_named_arg("version", ArgType.INTEGER, False, "Version to rollback to")
            .add_named_arg("env", ArgType.STRING, False, "Target environment",
                           allowed_values=["dev", "staging", "production"])
            .build()
        )

        registry.register(
            VerbSchema.Builder("review")
            .add_positional_arg("target", ArgType.STRING, True, "Review target")
            .add_named_arg("reviewer", ArgType.STRING, False, "Reviewer name")
            .add_named_arg("auto_merge", ArgType.BOOLEAN, False, "Auto-merge on approval")
            .build()
        )

        registry.register(
            VerbSchema.Builder("merge")
            .add_positional_arg("source", ArgType.STRING, True, "Source branch")
            .add_positional_arg("target", ArgType.STRING, True, "Target branch")
            .add_named_arg("strategy", ArgType.STRING, False, "Merge strategy",
                           allowed_values=["merge", "rebase", "squash"])
            .add_named_arg("squash", ArgType.BOOLEAN, False, "Squash commits")
            .build()
        )

        registry.register(
            VerbSchema.Builder("lint")
            .add_positional_arg("target", ArgType.STRING, True, "Lint target")
            .add_named_arg("fix", ArgType.BOOLEAN, False, "Auto-fix issues")
            .add_named_arg("config", ArgType.STRING, False, "Linter configuration")
            .build()
        )

        registry.register(
            VerbSchema.Builder("scan")
            .add_positional_arg("target", ArgType.STRING, True, "Scan target")
            .add_named_arg("scan_type", ArgType.STRING, False, "Type of scan",
                           allowed_values=["sast", "dast", "sca", "container"])
            .add_named_arg("severity", ArgType.STRING, False, "Minimum severity level",
                           allowed_values=["low", "medium", "high", "critical"])
            .build()
        )

        registry.register(
            VerbSchema.Builder("release")
            .add_positional_arg("version", ArgType.STRING, True, "Release version",
                                pattern=r"^\d+\.\d+\.\d+$")
            .add_named_arg("tag", ArgType.STRING, False, "Git tag")
            .add_named_arg("draft", ArgType.BOOLEAN, False, "Create as draft")
            .add_named_arg("notes", ArgType.STRING, False, "Release notes")
            .build()
        )

        registry.register(
            VerbSchema.Builder("provision")
            .add_positional_arg("resource", ArgType.STRING, True, "Resource to provision")
            .add_named_arg("provider", ArgType.STRING, False, "Cloud provider",
                           allowed_values=["aws", "gcp", "azure"])
            .add_named_arg("region", ArgType.STRING, False, "Deployment region")
            .add_named_arg("count", ArgType.INTEGER, False, "Number of instances",
                           min_value=1, max_value=100)
            .build()
        )

        registry.register(
            VerbSchema.Builder("monitor")
            .add_positional_arg("target", ArgType.STRING, True, "Monitor target")
            .add_named_arg("interval", ArgType.INTEGER, False, "Check interval in seconds",
                           min_value=1, max_value=86400)
            .add_named_arg("alert_threshold", ArgType.FLOAT, False, "Alert threshold value",
                           min_value=0.0, max_value=1.0)
            .build()
        )

        registry.register(
            VerbSchema.Builder("migrate")
            .add_positional_arg("target", ArgType.STRING, True, "Migration target")
            .add_named_arg("direction", ArgType.STRING, False, "Migration direction",
                           allowed_values=["up", "down"])
            .add_named_arg("version", ArgType.STRING, False, "Target version")
            .add_named_arg("dry_run", ArgType.BOOLEAN, False, "Dry run mode")
            .build()
        )

        return registry

    @staticmethod
    def get_verbs() -> list[str]:
        """Return the list of verbs defined in this profile."""
        return list(SoftwareDevProfile._VERBS)
