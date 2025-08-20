"""BAML-integrated Project Manager Agent for structured project planning."""

import asyncio
import os
from typing import Dict, Any, List, Optional
from pathlib import Path

from baml_client.baml_client import b
from baml_client.baml_client.types import (
    ProjectPlan,
    ProjectPhase,
    TechnologyStack,
    PhaseValidationResult,
    ProjectComplexityAnalysis,
    ProjectTemplate,
    EstimatedEffort,
    RiskLevel,
    GitStrategy
)

from .model_clients import get_default_model
from .tools import get_project_structure, read_file, list_files


class BAMLProjectManagerAgent:
    """BAML-integrated Project Manager Agent with structured outputs."""

    def __init__(self):
        """Initialize the BAML Project Manager agent."""
        self.model = get_default_model() or "claude-3-5-sonnet-20241022"

    async def create_project_plan(self, task: str, working_dir: str = ".") -> Dict[str, Any]:
        """Create a comprehensive project plan using BAML for structured output.

        Args:
            task: Description of the development task
            working_dir: Working directory to analyze for existing project context

        Returns:
            Dictionary containing the structured project plan
        """
        try:
            # Analyze existing project context
            existing_tech_stack = await self._analyze_existing_tech_stack(working_dir)

            # Generate project plan using BAML
            project_plan = await b.GenerateProjectPlan(
                task_description=task,
                working_directory=working_dir,
                existing_tech_stack=existing_tech_stack
            )

            # Validate each phase
            validated_phases = []
            for phase in project_plan.phases:
                validation = await self._validate_phase(phase, task)
                if validation.is_valid or validation.confidence_score > 0.7:
                    validated_phases.append(phase)
                else:
                    # Apply recommendations and retry
                    improved_phase = await self._improve_phase(phase, validation)
                    validated_phases.append(improved_phase)

            # Convert BAML types to dictionary for compatibility
            return self._convert_plan_to_dict(project_plan, validated_phases)

        except Exception as e:
            # Fallback to manual plan creation
            return await self._create_fallback_plan(task, working_dir, str(e))

    async def analyze_project_complexity(self, project_summary: str, tech_stack: List[str]) -> Dict[str, Any]:
        """Analyze project complexity using BAML.

        Args:
            project_summary: Summary of the project
            tech_stack: List of technologies being used

        Returns:
            Dictionary containing complexity analysis
        """
        try:
            # Convert tech stack strings to BAML enums
            technology_stack = self._convert_to_tech_stack_enums(tech_stack)

            complexity_analysis = await b.AnalyzeProjectComplexity(
                project_summary=project_summary,
                technology_stack=technology_stack
            )

            return self._convert_complexity_to_dict(complexity_analysis)

        except Exception as e:
            return {
                "error": f"Complexity analysis failed: {str(e)}",
                "overall_complexity": "moderate",
                "recommendations": ["Manual complexity assessment recommended"]
            }

    async def get_project_template(self, template_type: str, customizations: List[str]) -> Dict[str, Any]:
        """Get a project template with customizations.

        Args:
            template_type: Type of project template (e.g., "nextjs_dashboard")
            customizations: List of customization requirements

        Returns:
            Dictionary containing the templated project plan
        """
        try:
            # Convert string to BAML enum
            template_enum = self._convert_to_template_enum(template_type)

            project_plan = await b.GetProjectTemplate(
                template_type=template_enum,
                customizations=customizations
            )

            return self._convert_plan_to_dict(project_plan, project_plan.phases)

        except Exception as e:
            return await self._create_fallback_plan(
                f"Create {template_type} with customizations: {', '.join(customizations)}",
                ".",
                str(e)
            )

    async def _analyze_existing_tech_stack(self, working_dir: str) -> List[str]:
        """Analyze existing project to determine technology stack."""
        tech_stack = []

        try:
            # Check for common config files
            project_files = list_files(working_dir, "*")
            if project_files.get("success", False):
                files = project_files.get("files", [])

                if "package.json" in files:
                    tech_stack.extend(["Node.js", "JavaScript"])
                    # Read package.json to determine more specifics
                    package_json = read_file(os.path.join(working_dir, "package.json"))
                    if package_json.get("success", False):
                        content = package_json.get("content", "")
                        if "next" in content.lower():
                            tech_stack.append("Next.js")
                        if "react" in content.lower():
                            tech_stack.append("React")
                        if "typescript" in content.lower():
                            tech_stack.append("TypeScript")
                        if "tailwind" in content.lower():
                            tech_stack.append("Tailwind CSS")

                if "pyproject.toml" in files or "requirements.txt" in files:
                    tech_stack.append("Python")

                if "Dockerfile" in files:
                    tech_stack.append("Docker")

                if any(f.endswith(".sql") for f in files):
                    tech_stack.append("SQL Database")

        except Exception:
            pass

        return tech_stack if tech_stack else ["To be determined"]

    async def _validate_phase(self, phase: ProjectPhase, project_context: str) -> PhaseValidationResult:
        """Validate a project phase using BAML."""
        try:
            return await b.ValidatePhase(
                phase=phase,
                project_context=project_context
            )
        except Exception:
            # Return default validation if BAML fails
            return PhaseValidationResult(
                is_valid=True,
                confidence_score=0.8,
                issues=[],
                recommendations=[],
                adjusted_effort_estimate=None
            )

    async def _improve_phase(self, phase: ProjectPhase, validation: PhaseValidationResult) -> ProjectPhase:
        """Improve a phase based on validation feedback."""
        # Apply recommendations to improve the phase
        improved_phase = phase

        if validation.adjusted_effort_estimate:
            improved_phase.estimated_effort = validation.adjusted_effort_estimate

        # Add recommendations as additional acceptance criteria
        for recommendation in validation.recommendations:
            improved_phase.acceptance_criteria.append({
                "description": f"Address validation concern: {recommendation}",
                "testable": True,
                "priority": 3
            })

        return improved_phase

    def _convert_to_tech_stack_enums(self, tech_stack: List[str]) -> List[TechnologyStack]:
        """Convert string tech stack to BAML enums."""
        enum_mapping = {
            "next.js": TechnologyStack.NextJS,
            "nextjs": TechnologyStack.NextJS,
            "react": TechnologyStack.React,
            "typescript": TechnologyStack.TypeScript,
            "python": TechnologyStack.Python,
            "fastapi": TechnologyStack.FastAPI,
            "django": TechnologyStack.Django,
            "flask": TechnologyStack.Flask,
            "postgresql": TechnologyStack.PostgreSQL,
            "sqlite": TechnologyStack.SQLite,
            "mongodb": TechnologyStack.MongoDB,
            "redis": TechnologyStack.Redis,
            "docker": TechnologyStack.Docker,
            "node.js": TechnologyStack.NodeJS,
            "nodejs": TechnologyStack.NodeJS,
            "tailwind css": TechnologyStack.TailwindCSS,
            "tailwind": TechnologyStack.TailwindCSS,
            "shadcn/ui": TechnologyStack.ShadcnUI,
            "prisma": TechnologyStack.Prisma,
            "supabase": TechnologyStack.Supabase,
            "vercel": TechnologyStack.Vercel,
            "aws": TechnologyStack.AWS,
            "firebase": TechnologyStack.Firebase
        }

        result = []
        for tech in tech_stack:
            enum_val = enum_mapping.get(tech.lower())
            if enum_val and enum_val not in result:
                result.append(enum_val)

        return result if result else [TechnologyStack.TypeScript]  # Default fallback

    def _convert_to_template_enum(self, template_type: str) -> ProjectTemplate:
        """Convert string template type to BAML enum."""
        template_mapping = {
            "nextjs_dashboard": ProjectTemplate.NextJSDashboard,
            "python_api": ProjectTemplate.PythonAPI,
            "react_app": ProjectTemplate.ReactApp,
            "mobile_app": ProjectTemplate.MobileApp,
            "ml_pipeline": ProjectTemplate.MLPipeline,
            "ecommerce_store": ProjectTemplate.EcommerceStore,
            "blog_cms": ProjectTemplate.BlogCMS,
            "auth_system": ProjectTemplate.AuthSystem,
            "data_visualization": ProjectTemplate.DataVisualization,
            "microservice": ProjectTemplate.Microservice
        }

        return template_mapping.get(template_type.lower(), ProjectTemplate.NextJSDashboard)

    def _convert_plan_to_dict(self, project_plan: ProjectPlan, phases: List[ProjectPhase]) -> Dict[str, Any]:
        """Convert BAML ProjectPlan to dictionary format."""
        return {
            "project_summary": project_plan.project_summary,
            "technology_stack": [tech.value for tech in project_plan.technology_stack],
            "phases": [
                {
                    "phase_number": phase.phase_number,
                    "phase_name": phase.phase_name,
                    "description": phase.description,
                    "deliverables": [
                        {
                            "name": d.name,
                            "description": d.description,
                            "file_path": d.file_path,
                            "acceptance_criteria": [
                                {
                                    "description": ac.description,
                                    "testable": ac.testable,
                                    "priority": ac.priority
                                }
                                for ac in d.acceptance_criteria
                            ]
                        }
                        for d in phase.deliverables
                    ],
                    "estimated_effort": phase.estimated_effort.value,
                    "dependencies": [
                        {
                            "phase_number": dep.phase_number,
                            "description": dep.description,
                            "type": dep.type
                        }
                        for dep in phase.dependencies
                    ],
                    "git_strategy": phase.git_strategy.value,
                    "acceptance_criteria": [
                        {
                            "description": ac.description,
                            "testable": ac.testable,
                            "priority": ac.priority
                        }
                        for ac in phase.acceptance_criteria
                    ],
                    "potential_risks": [
                        {
                            "description": risk.description,
                            "level": risk.level.value,
                            "mitigation_strategy": risk.mitigation_strategy,
                            "impact": risk.impact
                        }
                        for risk in phase.potential_risks
                    ],
                    "prerequisites": phase.prerequisites,
                    "success_metrics": phase.success_metrics,
                    "status": phase.status.value
                }
                for phase in phases
            ],
            "integration_plan": {
                "strategy": project_plan.integration_plan.strategy,
                "testing_approach": project_plan.integration_plan.testing_approach,
                "deployment_steps": project_plan.integration_plan.deployment_steps,
                "rollback_plan": project_plan.integration_plan.rollback_plan,
                "monitoring_requirements": project_plan.integration_plan.monitoring_requirements
            },
            "deployment_considerations": {
                "environment_setup": project_plan.deployment_considerations.environment_setup,
                "infrastructure_requirements": project_plan.deployment_considerations.infrastructure_requirements,
                "security_considerations": project_plan.deployment_considerations.security_considerations,
                "performance_requirements": project_plan.deployment_considerations.performance_requirements,
                "scaling_considerations": project_plan.deployment_considerations.scaling_considerations,
                "backup_strategy": project_plan.deployment_considerations.backup_strategy,
                "monitoring_setup": project_plan.deployment_considerations.monitoring_setup
            },
            "total_estimated_effort": project_plan.total_estimated_effort,
            "critical_path_phases": project_plan.critical_path_phases,
            "success_metrics": project_plan.success_metrics,
            "assumptions": project_plan.assumptions,
            "constraints": project_plan.constraints,
            "stakeholders": project_plan.stakeholders,
            "budget_considerations": project_plan.budget_considerations,
            "timeline_milestones": project_plan.timeline_milestones,
            "baml_powered": True,
            "parsing_method": "BAML structured output"
        }

    def _convert_complexity_to_dict(self, complexity: ProjectComplexityAnalysis) -> Dict[str, Any]:
        """Convert BAML complexity analysis to dictionary."""
        return {
            "overall_complexity": complexity.overall_complexity.value,
            "dimensions": [
                {
                    "name": dim.name,
                    "level": dim.level.value,
                    "factors": dim.factors,
                    "mitigation_strategies": dim.mitigation_strategies,
                    "required_expertise": dim.required_expertise
                }
                for dim in complexity.dimensions
            ],
            "recommended_team_size": complexity.recommended_team_size,
            "recommended_timeline": complexity.recommended_timeline,
            "critical_success_factors": complexity.critical_success_factors,
            "major_risks": [
                {
                    "description": risk.description,
                    "level": risk.level.value,
                    "mitigation_strategy": risk.mitigation_strategy,
                    "impact": risk.impact
                }
                for risk in complexity.major_risks
            ],
            "technology_recommendations": complexity.technology_recommendations,
            "skill_requirements": complexity.skill_requirements
        }

    async def _create_fallback_plan(self, task: str, working_dir: str, error: str) -> Dict[str, Any]:
        """Create fallback plan when BAML fails."""
        # Intelligent fallback based on task analysis
        phases = []

        if "next.js" in task.lower() or "react" in task.lower():
            phases = [
                {
                    "phase_number": 1,
                    "phase_name": "Project Foundation",
                    "description": "Set up Next.js project with TypeScript and essential configuration",
                    "deliverables": ["package.json", "tsconfig.json", "next.config.js"],
                    "estimated_effort": "2-4 hours",
                    "dependencies": [],
                    "git_strategy": "create feature branch",
                    "acceptance_criteria": ["Project builds successfully", "TypeScript configured"],
                    "potential_risks": ["Version compatibility issues"],
                    "prerequisites": [],
                    "success_metrics": ["npm run build succeeds"],
                    "status": "planned"
                },
                {
                    "phase_number": 2,
                    "phase_name": "UI Foundation",
                    "description": "Implement core UI components and styling system",
                    "deliverables": ["Component library", "Styling configuration", "Layout components"],
                    "estimated_effort": "2-4 hours",
                    "dependencies": [{"phase_number": 1, "description": "Project setup", "type": "hard"}],
                    "git_strategy": "continue on feature branch",
                    "acceptance_criteria": ["Components render correctly", "Responsive design works"],
                    "potential_risks": ["Styling conflicts", "Component complexity"],
                    "prerequisites": ["Phase 1 completed"],
                    "success_metrics": ["UI components display properly"],
                    "status": "planned"
                },
                {
                    "phase_number": 3,
                    "phase_name": "Feature Implementation",
                    "description": "Build core application features and functionality",
                    "deliverables": ["Feature components", "Business logic", "API integration"],
                    "estimated_effort": "Half day (4 hours)",
                    "dependencies": [{"phase_number": 2, "description": "UI foundation", "type": "hard"}],
                    "git_strategy": "continue on feature branch",
                    "acceptance_criteria": ["Features work as expected", "Error handling implemented"],
                    "potential_risks": ["Complex business logic", "API integration issues"],
                    "prerequisites": ["Phase 2 completed"],
                    "success_metrics": ["All features functional"],
                    "status": "planned"
                }
            ]
        else:
            # Generic fallback
            phases = [
                {
                    "phase_number": 1,
                    "phase_name": "Analysis & Setup",
                    "description": "Analyze requirements and set up project structure",
                    "deliverables": ["Project structure", "Configuration files", "Dependencies"],
                    "estimated_effort": "2-4 hours",
                    "dependencies": [],
                    "git_strategy": "create feature branch",
                    "acceptance_criteria": ["Project structure established", "Build system working"],
                    "potential_risks": ["Unclear requirements", "Technical complexity"],
                    "prerequisites": [],
                    "success_metrics": ["Environment ready for development"],
                    "status": "planned"
                },
                {
                    "phase_number": 2,
                    "phase_name": "Core Implementation",
                    "description": "Implement main functionality according to requirements",
                    "deliverables": ["Core features", "Business logic", "Data models"],
                    "estimated_effort": "Half day (4 hours)",
                    "dependencies": [{"phase_number": 1, "description": "Project setup", "type": "hard"}],
                    "git_strategy": "continue on feature branch",
                    "acceptance_criteria": ["Core features work", "Basic testing passes"],
                    "potential_risks": ["Implementation complexity", "Performance issues"],
                    "prerequisites": ["Phase 1 completed"],
                    "success_metrics": ["Core functionality operational"],
                    "status": "planned"
                }
            ]

        return {
            "project_summary": task,
            "technology_stack": ["To be determined"],
            "phases": phases,
            "integration_plan": {
                "strategy": "Sequential phase execution with testing",
                "testing_approach": "Unit and integration testing per phase",
                "deployment_steps": ["Build", "Test", "Deploy"],
                "rollback_plan": "Git revert to previous stable commit",
                "monitoring_requirements": ["Build status", "Test results"]
            },
            "deployment_considerations": {
                "environment_setup": ["Development environment", "CI/CD pipeline"],
                "infrastructure_requirements": ["Hosting platform", "Database if needed"],
                "security_considerations": ["Input validation", "Authentication"],
                "performance_requirements": ["Load time optimization", "Responsive design"],
                "scaling_considerations": ["Code organization", "Performance monitoring"],
                "backup_strategy": "Git repository with regular commits",
                "monitoring_setup": ["Error tracking", "Performance monitoring"]
            },
            "total_estimated_effort": "1-2 days",
            "critical_path_phases": [1, 2],
            "success_metrics": ["All phases completed", "Quality standards met"],
            "assumptions": ["Requirements are clear", "Development environment available"],
            "constraints": ["Time limitations", "Resource availability"],
            "stakeholders": ["Development team", "Project stakeholders"],
            "budget_considerations": None,
            "timeline_milestones": {
                "Phase 1": "Day 1",
                "Phase 2": "Day 2",
                "Completion": "End of Day 2"
            },
            "baml_powered": False,
            "parsing_method": "Intelligent fallback",
            "fallback_reason": error
        }

    async def close(self):
        """Close any resources (BAML handles its own cleanup)."""
        pass
