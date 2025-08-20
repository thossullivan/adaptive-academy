"""Sample Python file for testing the Developer Crew."""

def add_numbers(a: int, b: int) -> int:
    """Add two numbers together.
    
    Args:
        a: First number
        b: Second number
        
    Returns:
        Sum of a and b
    """
    return a + b


def multiply_numbers(a: int, b: int) -> int:
    """Multiply two numbers.
    
    Args:
        a: First number  
        b: Second number
        
    Returns:
        Product of a and b
    """
    return a * b


if __name__ == "__main__":
    print("Testing basic math functions:")
    print(f"2 + 3 = {add_numbers(2, 3)}")
    print(f"4 * 5 = {multiply_numbers(4, 5)}")