import importlib.util
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parents[1] / "skills" / "jev-filter" / "scripts"
spec = importlib.util.spec_from_file_location("skill_workflow", HERE / "workflow.py")
workflow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(workflow)


class WorkflowTests(unittest.TestCase):
    def test_records_forces_filter_and_keeps_partial_process_exit(self):
        with (
            patch.object(workflow.shutil, "which", return_value="/safe/jev-filter"),
            patch.object(workflow.os, "execv") as execute,
        ):
            workflow.main(
                ["records", "--input", "-", "--task", "Find failures", "--analysis", "spec.json"]
            )
        command, argv = execute.call_args.args
        self.assertEqual(command, "/safe/jev-filter")
        self.assertEqual(argv[1], "query")
        self.assertEqual(argv[argv.index("--mode") + 1], "filter")
        self.assertIn("--analysis", argv)
        self.assertIn("--diagnostics", argv)

    def test_untrusted_values_remain_literal_arguments(self):
        task = "Select failures; $(touch forbidden) `id`"
        command = workflow.build_command(
            ["records", "--input", "-", "--task", task, "--analysis", "spec.json"]
        )
        self.assertIn(task, command)
        self.assertNotIn("sh", command)
        self.assertNotIn("-c", command)

    def test_code_query_adds_bounded_recall_and_caller_expansion(self):
        with tempfile.TemporaryDirectory() as root:
            command = workflow.build_command(
                [
                    "code",
                    "--root",
                    root,
                    "--query",
                    "DNS failure",
                    "--task",
                    "Find DNS handling",
                    "--expand-callers",
                ]
            )
        self.assertEqual(command[0], "code-search")
        self.assertIn("--query", command)
        self.assertIn("--expand-callers", command)
        self.assertEqual(command[command.index("--max-files") + 1], "2000")

    def test_diff_requires_explicit_scope_and_rejects_head_without_base(self):
        with tempfile.TemporaryDirectory() as root:
            for options in [[], ["--staged", "--unstaged"], ["--staged", "--head", "HEAD"]]:
                with self.assertRaises(SystemExit):
                    workflow.build_command(
                        ["diff", "--root", root, "--task", "Find changes", *options]
                    )
            command = workflow.build_command(
                [
                    "diff",
                    "--root",
                    root,
                    "--task",
                    "Find changes",
                    "--base",
                    "HEAD~1",
                    "--head",
                    "HEAD",
                ]
            )
        self.assertIn("HEAD~1", command)

    def test_logs_stdin_routes_once_without_a_shell_collector(self):
        command = workflow.build_command(
            ["logs", "--input", "-", "--task", "Classify synthetic failures"]
        )
        self.assertEqual(command[0], "triage")
        self.assertIn("-", command)
        self.assertNotIn("--collect", command)

    def test_rejects_actions_and_excess_concurrency(self):
        for verb in ["browse", "desktop", "exec", "delete", "confirm"]:
            with self.assertRaises(SystemExit):
                workflow.build_command([verb])
        for workers in ["0", "31"]:
            with self.assertRaises(SystemExit):
                workflow.build_command(
                    [
                        "records",
                        "--input",
                        "-",
                        "--task",
                        "Find records",
                        "--analysis",
                        "spec.json",
                        "--workers",
                        workers,
                    ]
                )

    def test_survey_planning_and_offline_eval_use_existing_cli(self):
        survey = workflow.build_command(
            ["survey", "--input", "records.json", "--spec", "survey.json", "--dry-run"]
        )
        self.assertEqual(survey[0], "survey")
        self.assertIn("--dry-run", survey)
        evaluation = workflow.build_command(["eval", "--input", "evaluation.json"])
        self.assertEqual(evaluation, ["eval", "--input", "evaluation.json"])

    def test_missing_cli_fails_without_forwarding_environment(self):
        with (
            patch.object(workflow.shutil, "which", return_value=None),
            patch.dict(os.environ, {"TYPESAFE_API_KEY": "synthetic-secret"}),
        ):
            with self.assertRaises(SystemExit) as caught:
                workflow.main(["eval", "--input", "fixture.json"])
        self.assertNotIn("synthetic-secret", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
