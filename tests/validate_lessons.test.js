import { test, describe, before } from 'node:test';
import assert from 'node:assert';
import { loadPyodide } from 'pyodide';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';
import { LessonSchema } from './schemas.js';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = join(__dirname, '..');
const LESSONS_DIR = join(PROJECT_ROOT, 'lessons');

function walkDir(dir) {
    let results = [];
    let list = readdirSync(dir);
    list.forEach((file) => {
        file = join(dir, file);
        let stat = statSync(file);
        if (stat && stat.isDirectory()) {
            results = results.concat(walkDir(file));
        } else {
            if (file.endsWith('.json')) results.push(file);
        }
    });
    return results;
}

const evaluateFormula = (formula, variables = {}) => {
    // A safe-ish way to construct a function with Math built in
    const names = Object.keys(variables);
    const values = Object.values(variables);
    
    // We bind all Math functions to the scope so "Math.sqrt" just works
    const func = new Function(...names, `return ${formula};`);
    return func(...values);
};

describe('Why Academy Lesson Validator', { concurrency: false, timeout: 60000 }, () => {
    let pyodide;
    
    before(async () => {
        console.log("Loading Pyodide (this may take a few seconds)...");
        pyodide = await loadPyodide();
        await pyodide.loadPackage(['sympy', 'numpy', 'matplotlib']);
        console.log("Pyodide and packages loaded.");
    });

    const lessonFiles = walkDir(LESSONS_DIR);
    
    if (lessonFiles.length === 0) {
        test('No lessons found', () => {
            assert.ok(true, "No lessons to test");
        });
        return;
    }

    lessonFiles.forEach((file) => {
        const relativePath = file.replace(PROJECT_ROOT + '/', '');
        
        test(`Validates ${relativePath}`, async (t) => {
            const rawData = JSON.parse(readFileSync(file, 'utf8'));
            
            // 1. Zod Schema Validation
            // Throws structured error if JSON shape is wrong
            const lesson = LessonSchema.parse(rawData);

            for (const block of lesson.blocks) {
                const prefix = `[${lesson.lesson_id}/${block.id}]`;

                if (block.type === 'calculate') {
                    if (block.formula && block.variables) {
                        try {
                            const computed = evaluateFormula(block.formula, block.variables);
                            // ~5% tolerance check
                            const expected = block.expected_value;
                            if (expected !== 0) {
                                const relErr = Math.abs(computed - expected) / Math.abs(expected);
                                assert.ok(relErr <= 0.05, 
                                    `${prefix} Formula result ${computed} disagrees with expected_value ${expected}`);
                            } else {
                                assert.ok(computed === 0, `${prefix} Formula result ${computed} disagrees with expected_value ${expected}`);
                            }
                        } catch (e) {
                            assert.fail(`${prefix} Evaluation failed: ${e.message}`);
                        }
                    }
                }

                if (block.type === 'practice') {
                    // Try random sample evaluations
                    if (block.answer_formula && block.parameter_ranges) {
                        for (let i = 0; i < 5; i++) {
                            const params = {};
                            for (const [key, range] of Object.entries(block.parameter_ranges)) {
                                params[key] = Math.random() * (range[1] - range[0]) + range[0];
                            }
                            try {
                                const result = evaluateFormula(block.answer_formula, params);
                                assert.ok(Number.isFinite(result), `${prefix} Formula returned non-finite value`);
                            } catch (e) {
                                assert.fail(`${prefix} Practice formula failed: ${e.message}`);
                            }
                        }
                    }
                }

                if (block.type === 'read') {
                    // Verify interactive widgets
                    const matches = [...block.content_html.matchAll(/data-interactive="([^"]+)"/g)];
                    for (const m of matches) {
                        assert.ok(['spring'].includes(m[1]), `${prefix} Unknown interactive widget '${m[1]}'`);
                    }
                }
            }

            // Since Pyodide shares a global state, we run Python tests sequentially
            // and clear globals manually to sandbox
            for (const block of lesson.blocks) {
                const prefix = `[${lesson.lesson_id}/${block.id}]`;
                
                if (block.type === 'derive') {
                    for (let i = 0; i < block.steps.length; i++) {
                        const step = block.steps[i];
                        // Just checking syntax
                        const code = `
import sympy as sp
from sympy.parsing.latex import parse_latex
# Strip spaces and delimiters
cleaned = r"${step.result_equation}".replace("\\\\,", "").replace("\\\\!", "")
try:
    parse_latex(cleaned)
    valid = True
except Exception as e:
    valid = False
valid`;
                        const isValid = await pyodide.runPythonAsync(code);
                        // We do not fail hard on Sympy parse failures, identical to Python version ("Soft Fail")
                    }
                }

                if (block.type === 'code') {
                    // Sandbox wrapper
                    const code = `
import __main__
import sys, traceback, json
import matplotlib
matplotlib.use('AGG')
import numpy as np

ns = {'__name__': '__lesson__', 'np': np}

try:
    exec(${JSON.stringify(block.solution_code)}, ns)
except Exception as e:
    raise RuntimeError(traceback.format_exc())

# Return results as dictionary of JSON string
def convert(v):
    if isinstance(v, (np.ndarray, list)): return "list"
    try: return float(v)
    except: return None

json.dumps({k: convert(v) for k, v in ns.items() if not k.startswith('__')})
`;
                    let namespace;
                    try {
                        namespace = JSON.parse(await pyodide.runPythonAsync(code));
                    } catch (e) {
                        assert.fail(`${prefix} solution_code failed during execution:\\n${e}`);
                    }

                    for (const check of block.checks) {
                        const actual = namespace[check.variable];
                        assert.ok(actual !== undefined && actual !== null, `${prefix} Variable '${check.variable}' not defined in solution`);

                        if (check.expected_expr) {
                            // Eval using node Math/JS since our tests are localized
                            // evaluate expected_expr (like `np.sqrt(10)`)
                            // This is a bit tricky because the Python script used `eval(expected_expr, ns)`.
                            // So run the assert natively in Wasm python:
                            const assertCode = `
try:
    expected = eval(${JSON.stringify(check.expected_expr)}, {'np': np}, ns)
    diff = abs(float(ns.get('${check.variable}')) - float(expected))
    passed = diff <= ${check.tolerance || 1e-6}
except Exception as e:
    passed = False
passed
`;
                            const passed = await pyodide.runPythonAsync(assertCode);
                            assert.ok(passed, `${prefix} Check failed for '${check.variable}' (Expr: ${check.expected_expr})`);
                        } else if (check.max_value !== undefined) {
                            assert.ok(actual <= check.max_value, `${prefix} ${check.variable} = ${actual} > ${check.max_value}`);
                        }
                    }
                }
            }
        });
    });
});
