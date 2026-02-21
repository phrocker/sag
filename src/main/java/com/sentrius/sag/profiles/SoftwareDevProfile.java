package com.sentrius.sag.profiles;

import com.sentrius.sag.SchemaRegistry;
import com.sentrius.sag.VerbSchema;
import com.sentrius.sag.VerbSchema.ArgType;

import java.util.List;

/**
 * Pre-built schema profile for common software development verbs.
 */
public class SoftwareDevProfile {

    private static final List<String> VERBS = List.of(
        "build", "test", "deploy", "rollback", "review", "merge",
        "lint", "scan", "release", "provision", "monitor", "migrate"
    );

    /**
     * Return a SchemaRegistry pre-populated with software development verb schemas.
     */
    public static SchemaRegistry createRegistry() {
        SchemaRegistry registry = new SchemaRegistry();

        registry.register(new VerbSchema.Builder("build")
            .addPositionalArg("target", ArgType.STRING, true, "Build target")
            .addNamedArg("config", ArgType.STRING, false, "Build configuration")
            .addNamedArg("clean", ArgType.BOOLEAN, false, "Clean before building")
            .build());

        registry.register(new VerbSchema.Builder("test")
            .addPositionalArg("suite", ArgType.STRING, true, "Test suite to run")
            .addNamedArg("coverage", ArgType.BOOLEAN, false, "Enable coverage reporting")
            .addNamedArg("timeout", ArgType.INTEGER, false, "Timeout in seconds",
                null, null, 1, 3600)
            .addNamedArg("parallel", ArgType.BOOLEAN, false, "Run tests in parallel")
            .build());

        registry.register(new VerbSchema.Builder("deploy")
            .addPositionalArg("app", ArgType.STRING, true, "Application to deploy")
            .addNamedArg("version", ArgType.INTEGER, false, "Version number")
            .addNamedArg("env", ArgType.STRING, false, "Target environment",
                List.of("dev", "staging", "production"), null, null, null)
            .addNamedArg("replicas", ArgType.INTEGER, false, "Number of replicas",
                null, null, 1, 100)
            .build());

        registry.register(new VerbSchema.Builder("rollback")
            .addPositionalArg("app", ArgType.STRING, true, "Application to rollback")
            .addNamedArg("version", ArgType.INTEGER, false, "Version to rollback to")
            .addNamedArg("env", ArgType.STRING, false, "Target environment",
                List.of("dev", "staging", "production"), null, null, null)
            .build());

        registry.register(new VerbSchema.Builder("review")
            .addPositionalArg("target", ArgType.STRING, true, "Review target")
            .addNamedArg("reviewer", ArgType.STRING, false, "Reviewer name")
            .addNamedArg("auto_merge", ArgType.BOOLEAN, false, "Auto-merge on approval")
            .build());

        registry.register(new VerbSchema.Builder("merge")
            .addPositionalArg("source", ArgType.STRING, true, "Source branch")
            .addPositionalArg("target", ArgType.STRING, true, "Target branch")
            .addNamedArg("strategy", ArgType.STRING, false, "Merge strategy",
                List.of("merge", "rebase", "squash"), null, null, null)
            .addNamedArg("squash", ArgType.BOOLEAN, false, "Squash commits")
            .build());

        registry.register(new VerbSchema.Builder("lint")
            .addPositionalArg("target", ArgType.STRING, true, "Lint target")
            .addNamedArg("fix", ArgType.BOOLEAN, false, "Auto-fix issues")
            .addNamedArg("config", ArgType.STRING, false, "Linter configuration")
            .build());

        registry.register(new VerbSchema.Builder("scan")
            .addPositionalArg("target", ArgType.STRING, true, "Scan target")
            .addNamedArg("scan_type", ArgType.STRING, false, "Type of scan",
                List.of("sast", "dast", "sca", "container"), null, null, null)
            .addNamedArg("severity", ArgType.STRING, false, "Minimum severity level",
                List.of("low", "medium", "high", "critical"), null, null, null)
            .build());

        registry.register(new VerbSchema.Builder("release")
            .addPositionalArg("version", ArgType.STRING, true, "Release version",
                null, "^\\d+\\.\\d+\\.\\d+$", null, null)
            .addNamedArg("tag", ArgType.STRING, false, "Git tag")
            .addNamedArg("draft", ArgType.BOOLEAN, false, "Create as draft")
            .addNamedArg("notes", ArgType.STRING, false, "Release notes")
            .build());

        registry.register(new VerbSchema.Builder("provision")
            .addPositionalArg("resource", ArgType.STRING, true, "Resource to provision")
            .addNamedArg("provider", ArgType.STRING, false, "Cloud provider",
                List.of("aws", "gcp", "azure"), null, null, null)
            .addNamedArg("region", ArgType.STRING, false, "Deployment region")
            .addNamedArg("count", ArgType.INTEGER, false, "Number of instances",
                null, null, 1, 100)
            .build());

        registry.register(new VerbSchema.Builder("monitor")
            .addPositionalArg("target", ArgType.STRING, true, "Monitor target")
            .addNamedArg("interval", ArgType.INTEGER, false, "Check interval in seconds",
                null, null, 1, 86400)
            .addNamedArg("alert_threshold", ArgType.FLOAT, false, "Alert threshold value",
                null, null, 0.0, 1.0)
            .build());

        registry.register(new VerbSchema.Builder("migrate")
            .addPositionalArg("target", ArgType.STRING, true, "Migration target")
            .addNamedArg("direction", ArgType.STRING, false, "Migration direction",
                List.of("up", "down"), null, null, null)
            .addNamedArg("version", ArgType.STRING, false, "Target version")
            .addNamedArg("dry_run", ArgType.BOOLEAN, false, "Dry run mode")
            .build());

        return registry;
    }

    /**
     * Return the list of verbs defined in this profile.
     */
    public static List<String> getVerbs() {
        return VERBS;
    }
}
