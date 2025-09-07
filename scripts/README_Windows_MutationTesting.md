# Windows-Friendly Mutation Testing Solutions

Since `mutmut` requires the `resource` module (not available on Windows), here are several working alternatives:

## 🚀 Quick Solutions

### Option 1: Ultra-Simple Mutation Testing (Recommended)
**Best for Windows - No external dependencies required**

```cmd
# Double-click or run in Command Prompt
scripts\run_ultra_simple_mutation.bat
```

**Or manually:**
```cmd
python tools/ultra_simple_mutator.py core/signal "python test.py" 30
```

### Option 2: PowerShell Script
```powershell
# Run specific package
.\scripts\Run-SimpleMutation.ps1 -Package "core/signal"

# Run all packages
.\scripts\Run-SimpleMutation.ps1 -AllPackages
```

## 📊 Understanding Results

### Mutation Score Interpretation
- **80%+**: Excellent - Tests catch most potential bugs
- **60-79%**: Good - Tests provide decent coverage
- **40-59%**: Fair - Some test improvements needed
- **0-39%**: Poor - Significant test gaps exist

### What Gets Tested
Our ultra-simple mutator tests:
- ✅ Comparison operators (`<`, `>`, `==`, `!=`)
- ✅ Boolean logic (`and`, `or`, `not`)
- ✅ Arithmetic operations (`+`, `-`, `*`, `//`)
- ✅ Simple conditional logic

## 🔧 How It Works

1. **Creates Simple Tests**: Generates standalone test cases
2. **Generates Mutants**: Makes small changes to source code
3. **Runs Tests**: Checks if tests catch the mutations
4. **Reports Results**: Shows mutation score and survival rates

## 📁 Output Structure

```
ultra_mutation_results/
├── ultra_mutation_results_signal_[timestamp].json
├── ultra_mutation_results_risk_[timestamp].json
└── ultra_mutation_results_core_aurora_[timestamp].json
```

## 🎯 Example Results

```json
{
  "total_files": 3,
  "total_mutants": 15,
  "killed_mutants": 12,
  "survived_mutants": 3,
  "mutation_score": 80.0,
  "timestamp": 1757244416.123
}
```

## 🔍 Improving Mutation Scores

If your mutation score is low, add tests that check:

### For Comparison Operators
```python
# Instead of just: assert x < y
assert x < y
assert not (x >= y)  # Equivalent but different mutation
```

### For Boolean Logic
```python
# Instead of just: assert a and b
assert a and b
assert not (not a or not b)  # De Morgan's law equivalent
```

### For Arithmetic
```python
# Instead of just: assert x + y == 10
assert x + y == 10
assert y + x == 10  # Commutativity check
```

## 🆚 Comparison with Traditional Tools

| Feature | mutmut | Our Ultra-Simple |
|---------|--------|------------------|
| Windows Compatible | ❌ | ✅ |
| Complex Mutations | ✅ | ❌ |
| Easy Setup | ❌ | ✅ |
| Fast Execution | ✅ | ✅ |
| No Dependencies | ❌ | ✅ |

## 🚦 When to Use Each Approach

### Use Ultra-Simple When:
- ✅ Working on Windows
- ✅ Need quick feedback on test quality
- ✅ Don't want to deal with Docker/WSL
- ✅ Testing basic logic and comparisons

### Use Traditional mutmut When:
- ✅ Working on Linux/macOS
- ✅ Need complex mutations (function calls, etc.)
- ✅ Have time for Docker/WSL setup
- ✅ Need comprehensive mutation analysis

## 🔧 Advanced Usage

### Custom Test Commands
```cmd
python tools/ultra_simple_mutator.py core/signal "pytest -v" 60
```

### Specific File Testing
```cmd
python tools/ultra_simple_mutator.py core/signal/score.py "python test.py" 30
```

### Integration with CI/CD
```yaml
# GitHub Actions (on Windows runner)
- name: Run Mutation Testing
  run: |
    python tools/ultra_simple_mutator.py core/signal "python test.py" 30
```

## 📈 Next Steps

1. **Run mutation testing** on your critical packages
2. **Review survived mutants** to identify test gaps
3. **Add targeted tests** for missed mutations
4. **Re-run** to improve mutation scores
5. **Aim for 70%+** mutation score for production code

## 🐛 Troubleshooting

### "Python not found"
- Install Python 3.8+ from python.org
- Add Python to PATH environment variable

### "Permission denied"
- Run Command Prompt as Administrator
- Or use PowerShell without admin rights

### "No mutants generated"
- Check that source files contain testable code
- Ensure files don't have complex imports
- Try with different source files

---

*This solution provides immediate mutation testing capability on Windows without requiring Docker, WSL, or complex setup.*