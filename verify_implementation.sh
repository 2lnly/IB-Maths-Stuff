#!/bin/bash
# Verification script to check that all implementation components are in place

echo "==================================================================="
echo "Verifying Incomplete Text Validation Implementation"
echo "==================================================================="
echo ""

# Check files exist
echo "✓ Checking files exist..."
files=(
    "validate_incomplete_text.py"
    "test_validator.py"
    "VALIDATION_README.md"
    "IMPLEMENTATION_SUMMARY.md"
    "requirements.txt"
    "web/templates/physics.html"
)

all_exist=true
for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "  ✓ $file"
    else
        echo "  ✗ $file NOT FOUND"
        all_exist=false
    fi
done

echo ""

# Check validator script is executable
echo "✓ Checking script permissions..."
if [ -x "validate_incomplete_text.py" ]; then
    echo "  ✓ validate_incomplete_text.py is executable"
else
    echo "  ✗ validate_incomplete_text.py is NOT executable"
    all_exist=false
fi

echo ""

# Check anthropic in requirements
echo "✓ Checking requirements.txt..."
if grep -q "anthropic" requirements.txt; then
    echo "  ✓ anthropic package found in requirements.txt"
else
    echo "  ✗ anthropic package NOT found in requirements.txt"
    all_exist=false
fi

echo ""

# Check CSS in physics.html
echo "✓ Checking CSS in physics.html..."
if grep -q "text-incomplete-warning" web/templates/physics.html; then
    echo "  ✓ CSS class .text-incomplete-warning found"
else
    echo "  ✗ CSS class .text-incomplete-warning NOT found"
    all_exist=false
fi

echo ""

# Check JavaScript in physics.html
echo "✓ Checking JavaScript in physics.html..."
if grep -q "question.text_incomplete" web/templates/physics.html; then
    echo "  ✓ JavaScript logic for text_incomplete found"
else
    echo "  ✗ JavaScript logic for text_incomplete NOT found"
    all_exist=false
fi

echo ""

# Test Python syntax
echo "✓ Checking Python syntax..."
if python3 -m py_compile validate_incomplete_text.py 2>/dev/null; then
    echo "  ✓ validate_incomplete_text.py syntax OK"
else
    echo "  ✗ validate_incomplete_text.py has syntax errors"
    all_exist=false
fi

if python3 -m py_compile test_validator.py 2>/dev/null; then
    echo "  ✓ test_validator.py syntax OK"
else
    echo "  ✗ test_validator.py has syntax errors"
    all_exist=false
fi

echo ""

# Summary
echo "==================================================================="
if [ "$all_exist" = true ]; then
    echo "✅ All checks passed! Implementation is complete."
    echo ""
    echo "Next steps:"
    echo "  1. Run test: python3 test_validator.py"
    echo "  2. Run validation: export ANTHROPIC_API_KEY='your-key' && python3 validate_incomplete_text.py"
    echo "  3. Test frontend: cd web && python3 app.py"
    echo "  4. Review VALIDATION_README.md for full instructions"
else
    echo "❌ Some checks failed. Please review the errors above."
fi
echo "==================================================================="
