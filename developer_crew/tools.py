"""File system and execution tools for the developer crew agents."""

import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, Any, Optional, List


def read_file(file_path: str) -> Dict[str, Any]:
    """Read a file and return its contents.
    
    Args:
        file_path: Path to the file to read
        
    Returns:
        Dictionary with success status, content, and optional error message
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "content": "",
                "error": f"File does not exist: {file_path}"
            }
        
        content = path.read_text(encoding="utf-8")
        return {
            "success": True,
            "content": content,
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "content": "",
            "error": f"Error reading file {file_path}: {str(e)}"
        }


def write_file(file_path: str, content: str, create_dirs: bool = True) -> Dict[str, Any]:
    """Write content to a file.
    
    Args:
        file_path: Path to the file to write
        content: Content to write to the file
        create_dirs: Whether to create parent directories if they don't exist
        
    Returns:
        Dictionary with success status and optional error message
    """
    try:
        path = Path(file_path)
        
        if create_dirs:
            path.parent.mkdir(parents=True, exist_ok=True)
        
        path.write_text(content, encoding="utf-8")
        return {
            "success": True,
            "error": None,
            "message": f"Successfully wrote {len(content)} characters to {file_path}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error writing file {file_path}: {str(e)}"
        }


def edit_file(file_path: str, old_content: str, new_content: str) -> Dict[str, Any]:
    """Edit a file by replacing old_content with new_content.
    
    Args:
        file_path: Path to the file to edit
        old_content: Content to replace
        new_content: Content to replace with
        
    Returns:
        Dictionary with success status and optional error message
    """
    try:
        path = Path(file_path)
        if not path.exists():
            return {
                "success": False,
                "error": f"File does not exist: {file_path}"
            }
        
        current_content = path.read_text(encoding="utf-8")
        
        if old_content not in current_content:
            return {
                "success": False,
                "error": f"Old content not found in file: {file_path}"
            }
        
        new_file_content = current_content.replace(old_content, new_content)
        path.write_text(new_file_content, encoding="utf-8")
        
        return {
            "success": True,
            "error": None,
            "message": f"Successfully edited {file_path}"
        }
    except Exception as e:
        return {
            "success": False,
            "error": f"Error editing file {file_path}: {str(e)}"
        }


def list_files(directory_path: str, pattern: str = "*") -> Dict[str, Any]:
    """List files in a directory.
    
    Args:
        directory_path: Path to the directory to list
        pattern: Glob pattern to match files (default: "*")
        
    Returns:
        Dictionary with success status, list of files, and optional error message
    """
    try:
        path = Path(directory_path)
        if not path.exists():
            return {
                "success": False,
                "files": [],
                "error": f"Directory does not exist: {directory_path}"
            }
        
        if not path.is_dir():
            return {
                "success": False,
                "files": [],
                "error": f"Path is not a directory: {directory_path}"
            }
        
        files = [str(f) for f in path.glob(pattern) if f.is_file()]
        return {
            "success": True,
            "files": files,
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "files": [],
            "error": f"Error listing files in {directory_path}: {str(e)}"
        }


def get_project_structure(root_path: str = ".", max_depth: int = 3) -> Dict[str, Any]:
    """Get an overview of the project structure.
    
    Args:
        root_path: Root directory to analyze (default: current directory)
        max_depth: Maximum depth to traverse (default: 3)
        
    Returns:
        Dictionary with success status, structure info, and optional error message
    """
    try:
        path = Path(root_path)
        if not path.exists():
            return {
                "success": False,
                "structure": {},
                "error": f"Path does not exist: {root_path}"
            }
        
        structure = {}
        
        def build_structure(current_path: Path, current_depth: int):
            if current_depth > max_depth:
                return
            
            items = []
            try:
                for item in current_path.iterdir():
                    if item.name.startswith('.'):
                        continue
                    
                    if item.is_file():
                        items.append(f"📄 {item.name}")
                    elif item.is_dir():
                        items.append(f"📁 {item.name}/")
                        if current_depth < max_depth:
                            sub_structure = {}
                            build_structure(item, current_depth + 1)
            except PermissionError:
                items.append("❌ Permission denied")
            
            structure[str(current_path)] = items
        
        build_structure(path, 0)
        
        return {
            "success": True,
            "structure": structure,
            "error": None
        }
    except Exception as e:
        return {
            "success": False,
            "structure": {},
            "error": f"Error analyzing project structure: {str(e)}"
        }


def execute_command(
    command: str, 
    working_dir: Optional[str] = None, 
    timeout: int = 30,
    capture_output: bool = True
) -> Dict[str, Any]:
    """Execute a shell command and return the result.
    
    Args:
        command: Shell command to execute
        working_dir: Directory to run the command in (default: current directory)
        timeout: Timeout in seconds (default: 30)
        capture_output: Whether to capture stdout/stderr (default: True)
        
    Returns:
        Dictionary with success status, output, error, and return code
    """
    try:
        # Security check - only allow safe commands
        if not _is_safe_command(command):
            return {
                "success": False,
                "stdout": "",
                "stderr": "Command not allowed for security reasons",
                "return_code": -1,
                "command": command
            }
        
        # Set working directory
        cwd = working_dir if working_dir else os.getcwd()
        
        # Execute command
        result = subprocess.run(
            command,
            shell=True,
            cwd=cwd,
            timeout=timeout,
            capture_output=capture_output,
            text=True
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
            "command": command,
            "working_dir": cwd
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Command timed out after {timeout} seconds",
            "return_code": -1,
            "command": command
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Error executing command: {str(e)}",
            "return_code": -1,
            "command": command
        }


def run_python_script(
    script_path: str, 
    args: Optional[List[str]] = None, 
    working_dir: Optional[str] = None,
    timeout: int = 30
) -> Dict[str, Any]:
    """Run a Python script and return the result.
    
    Args:
        script_path: Path to the Python script to run
        args: Optional list of arguments to pass to the script
        working_dir: Directory to run the script in (default: current directory)
        timeout: Timeout in seconds (default: 30)
        
    Returns:
        Dictionary with success status, output, error, and return code
    """
    try:
        # Check if file exists
        script_path_obj = Path(script_path)
        if not script_path_obj.exists():
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Python script not found: {script_path}",
                "return_code": -1,
                "command": f"python {script_path}"
            }
        
        # Build command
        cmd_parts = [sys.executable, str(script_path_obj)]
        if args:
            cmd_parts.extend(args)
        
        command = " ".join(f'"{part}"' if " " in part else part for part in cmd_parts)
        
        return execute_command(command, working_dir, timeout)
        
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Error running Python script: {str(e)}",
            "return_code": -1,
            "command": f"python {script_path}"
        }


def run_tests(
    test_path: Optional[str] = None, 
    test_framework: str = "pytest",
    working_dir: Optional[str] = None,
    timeout: int = 120
) -> Dict[str, Any]:
    """Run tests using a specified testing framework.
    
    Args:
        test_path: Path to tests (default: auto-detect)
        test_framework: Testing framework to use ("pytest", "unittest", "nose")
        working_dir: Directory to run tests in (default: current directory)
        timeout: Timeout in seconds (default: 120)
        
    Returns:
        Dictionary with success status, output, error, and return code
    """
    try:
        # Auto-detect test path if not provided
        if not test_path:
            cwd = Path(working_dir) if working_dir else Path.cwd()
            
            # Common test directory patterns
            test_dirs = ["tests", "test", "testing", "spec"]
            for test_dir in test_dirs:
                if (cwd / test_dir).exists():
                    test_path = test_dir
                    break
            
            if not test_path:
                # Look for test files in current directory
                test_files = list(cwd.glob("test_*.py")) + list(cwd.glob("*_test.py"))
                if test_files:
                    test_path = "."
        
        # Build test command based on framework
        if test_framework == "pytest":
            command = f"pytest {test_path or '.'} -v"
        elif test_framework == "unittest":
            command = f"python -m unittest discover {test_path or '.'}"
        elif test_framework == "nose":
            command = f"nosetests {test_path or '.'}"
        else:
            return {
                "success": False,
                "stdout": "",
                "stderr": f"Unknown test framework: {test_framework}",
                "return_code": -1,
                "command": ""
            }
        
        return execute_command(command, working_dir, timeout)
        
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"Error running tests: {str(e)}",
            "return_code": -1,
            "command": f"{test_framework} {test_path or '.'}"
        }


def check_code_quality(
    file_or_dir: str,
    tools: Optional[List[str]] = None,
    working_dir: Optional[str] = None,
    timeout: int = 60
) -> Dict[str, Any]:
    """Run code quality checks using various tools.
    
    Args:
        file_or_dir: File or directory to check
        tools: List of tools to use ("ruff", "mypy", "black", "flake8") 
        working_dir: Directory to run checks in (default: current directory)
        timeout: Timeout in seconds (default: 60)
        
    Returns:
        Dictionary with results for each tool
    """
    if tools is None:
        tools = ["ruff", "mypy"]  # Default to common tools
    
    results = {
        "overall_success": True,
        "tool_results": {},
        "summary": []
    }
    
    for tool in tools:
        try:
            if tool == "ruff":
                command = f"ruff check {file_or_dir}"
            elif tool == "mypy":
                command = f"mypy {file_or_dir}"
            elif tool == "black":
                command = f"black --check {file_or_dir}"
            elif tool == "flake8":
                command = f"flake8 {file_or_dir}"
            else:
                results["tool_results"][tool] = {
                    "success": False,
                    "error": f"Unknown tool: {tool}"
                }
                continue
            
            result = execute_command(command, working_dir, timeout)
            results["tool_results"][tool] = result
            
            if not result["success"]:
                results["overall_success"] = False
                results["summary"].append(f"{tool}: FAILED")
            else:
                results["summary"].append(f"{tool}: PASSED")
                
        except Exception as e:
            results["tool_results"][tool] = {
                "success": False,
                "error": f"Error running {tool}: {str(e)}"
            }
            results["overall_success"] = False
            results["summary"].append(f"{tool}: ERROR")
    
    return results


def _is_safe_command(command: str) -> bool:
    """Check if a command is safe to execute.
    
    Args:
        command: Command to check
        
    Returns:
        True if command is considered safe
    """
    # List of dangerous commands/patterns to block
    dangerous_patterns = [
        "rm -rf",
        "sudo",
        "chmod 777",
        ">/dev/null",
        "&& rm",
        "; rm",
        "| rm",
        "curl",
        "wget",
        "dd if=",
        "mkfs",
        "format",
        "fdisk",
        "kill -9",
        "killall",
        "shutdown",
        "reboot",
        "halt",
        "init 0",
        "init 6",
        "> /etc/",
        ">> /etc/",
        "mv /etc/",
        "cp /etc/",
    ]
    
    # Convert to lowercase for checking
    cmd_lower = command.lower()
    
    # Check for dangerous patterns
    for pattern in dangerous_patterns:
        if pattern in cmd_lower:
            return False
    
    # Allow specific safe commands for development
    safe_commands = [
        "python", "pytest", "ruff", "mypy", "black", "flake8",
        "npm", "node", "yarn", "pip", "uv", "poetry",
        "git", "ls", "pwd", "echo", "cat", "grep", "find",
        "mkdir", "touch", "cp", "mv", "head", "tail",
        "which", "whereis", "type", "file", "wc", "sort",
        "uniq", "cut", "sed", "awk"
    ]
    
    # Extract the first word (command name)
    first_word = cmd_lower.split()[0] if cmd_lower.split() else ""
    
    # Check if the command starts with a safe command
    for safe_cmd in safe_commands:
        if first_word == safe_cmd or first_word.endswith(f"/{safe_cmd}"):
            return True
    
    # Also allow full paths to Python executables
    if "python" in first_word and ("/python" in first_word or "\\python" in first_word):
        return True
    
    # Default to unsafe if not explicitly allowed
    return False