"""Simple BAML-powered Project Manager for testing integration."""

import asyncio
from typing import Dict, Any, List
from baml_client.baml_client import b
from .tools import get_project_structure, list_files


class SimpleBAMLProjectManager:
    """Simple BAML-integrated Project Manager for testing."""

    async def create_project_plan(self, task: str, working_dir: str = ".") -> Dict[str, Any]:
        """Create a project plan using BAML structured output."""
        try:
            # Analyze existing project structure
            existing_tech_stack = self._analyze_tech_stack(working_dir)

            # Generate project plan using BAML
            plan = await b.GenerateProjectPlan(
                task_description=task,
                working_directory=working_dir,
                existing_tech_stack=existing_tech_stack
            )

            # Convert BAML response to dictionary
            return {
                "project_summary": plan.project_summary,
                "technology_stack": [tech.name for tech in plan.technology_stack],
                "phases": [
                    {
                        "phase_number": phase.phase_number,
                        "phase_name": phase.phase_name,
                        "description": phase.description,
                        "deliverables": [
                            {
                                "name": d.name,
                                "description": d.description,
                                "file_path": d.file_path
                            } for d in phase.deliverables
                        ],
                        "estimated_effort": phase.estimated_effort.name,
                        "git_strategy": phase.git_strategy.name,
                        "potential_risks": [
                            {
                                "description": r.description,
                                "level": r.level.name,
                                "mitigation_strategy": r.mitigation_strategy
                            } for r in phase.potential_risks
                        ]
                    } for phase in plan.phases
                ],
                "total_estimated_effort": plan.total_estimated_effort,
                "success_metrics": plan.success_metrics,
                "baml_powered": True
            }

        except Exception as e:
            # Fallback to simple structure
            return {
                "project_summary": task,
                "technology_stack": ["To be determined"],
                "phases": [
                    {
                        "phase_number": 1,
                        "phase_name": "Setup & Implementation",
                        "description": "Set up project structure and implement core functionality",
                        "deliverables": [{"name": "Core implementation", "description": "Main project files"}],
                        "estimated_effort": "TwoToFourHours",
                        "git_strategy": "FeatureBranch",
                        "potential_risks": []
                    }
                ],
                "total_estimated_effort": "2-4 hours",
                "success_metrics": ["Project completed successfully"],
                "baml_powered": False,
                "error": str(e)
            }

    def _analyze_tech_stack(self, working_dir: str) -> List[str]:
        """Simple tech stack analysis."""
        try:
            files_result = list_files(working_dir, "*")
            if files_result.get("success"):
                files = files_result.get("files", [])
                tech_stack = []

                if "package.json" in files:
                    tech_stack.extend(["NodeJS", "JavaScript"])
                if "tsconfig.json" in files:
                    tech_stack.append("TypeScript")
                if "next.config.js" in files:
                    tech_stack.append("NextJS")
                if "tailwind.config.js" in files:
                    tech_stack.append("TailwindCSS")
                if "pyproject.toml" in files:
                    tech_stack.append("Python")

                return tech_stack
        except:
            pass

        return ["Unknown"]

    async def close(self):
        """Cleanup method for compatibility."""
        pass
