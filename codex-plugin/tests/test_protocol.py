"""Exercise the installed SDK over real stdio, with no network or provider."""

import asyncio
import json
import sys
import tempfile
import unittest
from pathlib import Path

from mcp import ClientSession, StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parents[1]


class ProtocolTests(unittest.TestCase):
    def test_project_selection_does_not_use_process_cwd(self):
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                project = Path(directory) / "example-project"
                other = Path(directory) / "another-project"
                project.mkdir()
                other.mkdir()
                params = StdioServerParameters(
                    command=sys.executable,
                    args=[str(ROOT / "launch.py")],
                    cwd=str(project),
                    env={"AWM_ADM_URL": "http://invalid.invalid:9527"},
                )
                async with stdio_client(params) as (read, write):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        tools = (await session.list_tools()).tools
                        self.assertEqual(
                            [t.name for t in tools],
                            ["adm_status", "adm_project", "adm_ask", "adm_teach", "adm_work", "adm_set_mode"],
                        )
                        self.assertTrue(tools[0].annotations.read_only_hint)
                        cases = [
                            ({}, "no_project"),
                            ({"project_root": str(project)}, "invalid_endpoint"),
                            ({"workspace_roots": [str(project), str(other)]}, "choose_project"),
                            ({"workspace_roots": [str(project)]}, "invalid_endpoint"),
                            ({"project_root": "relative"}, "invalid_project"),
                            ({"project_root": str(project / "missing")}, "invalid_project"),
                            ({"project_root": str(ROOT)}, "invalid_project"),
                        ]
                        for arguments, state in cases:
                            result = await session.call_tool("adm_status", arguments)
                            self.assertFalse(result.is_error, result)
                            value = result.structured_content
                            self.assertEqual(value["state"], state)

        asyncio.run(check())

    def test_package_server_and_skill_dependency_agree(self):
        config = json.loads((ROOT / "mcp.json").read_text())
        self.assertEqual(list(config["mcpServers"]), ["awm-adm"])
        dependency = (ROOT / "skills/adm-project/agents/openai.yaml").read_text()
        self.assertIn('value: "awm-adm"', dependency)


if __name__ == "__main__":
    unittest.main()
