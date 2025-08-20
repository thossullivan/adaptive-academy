"""File system tools for the developer crew agents."""

import os
from pathlib import Path
from typing import Dict, Any, Optional


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