"""
Calculator extension — evaluates math expressions.
Matches: "calc 2+2", "calculate 100/3", "= 2**10", "math sin(0.5)"
"""

import re
import uuid
import math


# Safe subset of builtins for eval
_SAFE_GLOBALS = {
    "__builtins__": {},
    "abs": abs, "round": round, "min": min, "max": max, "sum": sum,
    "int": int, "float": float, "pow": pow,
    "pi": math.pi, "e": math.e, "tau": math.tau,
    "sqrt": math.sqrt, "log": math.log, "log2": math.log2, "log10": math.log10,
    "sin": math.sin, "cos": math.cos, "tan": math.tan,
    "asin": math.asin, "acos": math.acos, "atan": math.atan,
    "ceil": math.ceil, "floor": math.floor,
    "factorial": math.factorial, "gcd": math.gcd,
}


def match(text):
    patterns = [
        r"^(?:calc|calculate|compute|eval)\s+(.+)",
        r"^=\s*(.+)",
        r"^math\s+(.+)",
        r"^what\s+is\s+([\d\.\+\-\*\/\(\)\s\^%]+)$",
        r"^how\s+much\s+is\s+([\d\.\+\-\*\/\(\)\s\^%]+)$",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            return m.group(1).strip()
    return None


def action(original_text, expression):
    try:
        # Replace ^ with ** for exponentiation
        safe_expr = expression.replace("^", "**")
        result = eval(safe_expr, _SAFE_GLOBALS)
        # Format nicely
        if isinstance(result, float):
            if result == int(result) and abs(result) < 1e15:
                display = str(int(result))
            else:
                display = f"{result:.10g}"
        else:
            display = str(result)
    except Exception as e:
        display = f"Error: {e}"

    return {
        "type": "RENDER_WIDGET",
        "widget_id": f"calc-{uuid.uuid4().hex[:6]}",
        "widget_type": "calculator",
        "x": 400,
        "y": 280,
        "w": 320,
        "h": 160,
        "props": {"expression": expression, "result": display},
    }


EXTENSION = {
    "name": "calculator",
    "match": match,
    "action": action,
    "help": {
        "title": "Calculator",
        "icon": "🧮",
        "description": "Evaluate math expressions (trig, log, constants)",
        "examples": ["calc 2+2", "= pi * 2", "math sqrt(144)"],
    },
}
