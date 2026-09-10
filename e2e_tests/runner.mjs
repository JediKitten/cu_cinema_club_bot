#!/usr/bin/env node
/**
 * ==============================================================================
 * CU Cinema Club E2E Test Suite — Automated Test Runner & Assertion Harness
 * ==============================================================================
 * Zero-dependency Node.js ESM test harness designed for cu_cinema_club Redesign.
 *
 * Features:
 * - Clean, standalone assertion library (assertEqual, assertTrue, assertDeepEqual, etc.)
 * - Hierarchical test registration (suite/describe, test/it, beforeEach, afterEach, hooks)
 * - Precise performance timing via performance.now()
 * - Cinematic dark theme ANSI output formatting with gold accent (#e5a93c)
 * - Sequential execution across all 4 tiers (Feature, Boundary, Pairwise, Real-World)
 * - Per-tier and global statistics aggregation with threshold validation
 * - Standard exit codes: 0 on full pass with thresholds satisfied, 1 on any failure
 * - CLI flags: --tier=N, --bail, --grep=pattern, --no-color, --verbose
 * - Direct execution of runner OR individual test files
 * ==============================================================================
 */

import { isDeepStrictEqual, inspect } from 'node:util';
import { fileURLToPath, pathToFileURL } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

// --- CLI & Configuration Options ----------------------------------------------

const args = process.argv.slice(2);
const options = {
  tierFilter: null,
  bail: false,
  grep: null,
  noColor: process.env.NO_COLOR !== undefined || args.includes('--no-color'),
  verbose: args.includes('--verbose') || args.includes('-v'),
  timeout: 10000 // 10s per test
};

for (let i = 0; i < args.length; i++) {
  const arg = args[i];
  if (arg.startsWith('--tier=')) {
    options.tierFilter = parseInt(arg.split('=')[1], 10);
  } else if (arg === '-t' && args[i + 1]) {
    options.tierFilter = parseInt(args[++i], 10);
  } else if (arg === '--bail' || arg === '-b') {
    options.bail = true;
  } else if (arg.startsWith('--grep=')) {
    options.grep = new RegExp(arg.split('=')[1], 'i');
  } else if (arg === '-g' && args[i + 1]) {
    options.grep = new RegExp(args[++i], 'i');
  }
}

// --- Cinematic Dark ANSI Styling ----------------------------------------------

const colors = options.noColor
  ? {
      reset: '',
      bold: '',
      dim: '',
      italic: '',
      underline: '',
      red: '',
      green: '',
      yellow: '',
      blue: '',
      magenta: '',
      cyan: '',
      gray: '',
      gold: '',
      bgRed: '',
      bgGreen: ''
    }
  : {
      reset: '\x1b[0m',
      bold: '\x1b[1m',
      dim: '\x1b[2m',
      italic: '\x1b[3m',
      underline: '\x1b[4m',
      red: '\x1b[31m',
      green: '\x1b[32m',
      yellow: '\x1b[33m',
      blue: '\x1b[34m',
      magenta: '\x1b[35m',
      cyan: '\x1b[36m',
      gray: '\x1b[90m',
      gold: '\x1b[38;2;229;169;60m', // Cinematic gold accent #e5a93c
      bgRed: '\x1b[41m',
      bgGreen: '\x1b[42m'
    };

// --- Custom Assertion Library -------------------------------------------------

export class AssertionError extends Error {
  constructor(message, actual, expected, operator) {
    super(message);
    this.name = 'AssertionError';
    this.actual = actual;
    this.expected = expected;
    this.operator = operator;
    if (Error.captureStackTrace) {
      Error.captureStackTrace(this, this.constructor);
    }
  }
}

function formatValue(v) {
  return inspect(v, { depth: 5, colors: !options.noColor, compact: true, breakLength: 60 });
}

function formatIndented(v) {
  const str = inspect(v, { depth: 8, colors: !options.noColor, compact: false });
  return str.split('\n').map(line => '    ' + line).join('\n');
}

export function assertEqual(actual, expected, message) {
  if (actual !== expected) {
    throw new AssertionError(
      message || `Expected ${formatValue(expected)}, but got ${formatValue(actual)}`,
      actual,
      expected,
      'assertEqual'
    );
  }
}

export function assertNotEqual(actual, expected, message) {
  if (actual === expected) {
    throw new AssertionError(
      message || `Expected values to differ, but both are ${formatValue(actual)}`,
      actual,
      expected,
      'assertNotEqual'
    );
  }
}

export function assertTrue(value, message) {
  if (value !== true) {
    throw new AssertionError(
      message || `Expected boolean true, but got ${formatValue(value)}`,
      value,
      true,
      'assertTrue'
    );
  }
}

export function assertFalse(value, message) {
  if (value !== false) {
    throw new AssertionError(
      message || `Expected boolean false, but got ${formatValue(value)}`,
      value,
      false,
      'assertFalse'
    );
  }
}

export function assertDeepEqual(actual, expected, message) {
  if (!isDeepStrictEqual(actual, expected)) {
    const diffText = `\n  Expected:\n${formatIndented(expected)}\n  Actual:\n${formatIndented(actual)}`;
    throw new AssertionError(
      (message ? `${message}\n` : 'Structural deep equality mismatch:\n') + diffText,
      actual,
      expected,
      'assertDeepEqual'
    );
  }
}

export function assertThrows(fn, expectedError, message) {
  let threw = false;
  let thrownError = null;
  try {
    fn();
  } catch (err) {
    threw = true;
    thrownError = err;
  }
  if (!threw) {
    throw new AssertionError(
      message || 'Expected synchronous function to throw an error, but it returned normally',
      null,
      expectedError || 'Error',
      'assertThrows'
    );
  }
  if (expectedError) {
    verifyErrorMatch(thrownError, expectedError, message);
  }
}

export async function assertRejects(fn, expectedError, message) {
  let threw = false;
  let thrownError = null;
  try {
    const promise = typeof fn === 'function' ? fn() : fn;
    await promise;
  } catch (err) {
    threw = true;
    thrownError = err;
  }
  if (!threw) {
    throw new AssertionError(
      message || 'Expected asynchronous function to reject, but it resolved successfully',
      null,
      expectedError || 'Error',
      'assertRejects'
    );
  }
  if (expectedError) {
    verifyErrorMatch(thrownError, expectedError, message);
  }
}

function verifyErrorMatch(thrownError, expectedError, message) {
  if (typeof expectedError === 'function') {
    if (!(thrownError instanceof expectedError)) {
      throw new AssertionError(
        message || `Expected error of type ${expectedError.name}, but caught ${thrownError?.constructor?.name || typeof thrownError}`,
        thrownError,
        expectedError,
        'assertThrows'
      );
    }
  } else if (expectedError instanceof RegExp) {
    const errStr = thrownError?.message || String(thrownError);
    if (!expectedError.test(errStr)) {
      throw new AssertionError(
        message || `Expected error message to match ${expectedError}, but got "${errStr}"`,
        errStr,
        expectedError.toString(),
        'assertThrows'
      );
    }
  } else if (typeof expectedError === 'string') {
    const errStr = thrownError?.message || String(thrownError);
    if (!errStr.includes(expectedError)) {
      throw new AssertionError(
        message || `Expected error message to contain "${expectedError}", but got "${errStr}"`,
        errStr,
        expectedError,
        'assertThrows'
      );
    }
  }
}

export function assertMatches(str, regex, message) {
  if (typeof str !== 'string') {
    throw new AssertionError(
      message || `Expected string input for assertMatches, but got ${typeof str}`,
      str,
      regex,
      'assertMatches'
    );
  }
  const reg = regex instanceof RegExp ? regex : new RegExp(regex);
  if (!reg.test(str)) {
    throw new AssertionError(
      message || `Expected string "${str}" to match pattern ${reg}`,
      str,
      reg.toString(),
      'assertMatches'
    );
  }
}

export function assertInDelta(actual, expected, delta = 0.001, message) {
  if (typeof actual !== 'number' || typeof expected !== 'number' || typeof delta !== 'number') {
    throw new AssertionError(
      'assertInDelta requires numeric values for actual, expected, and delta tolerance',
      { actual, expected, delta },
      'number',
      'assertInDelta'
    );
  }
  const diff = Math.abs(actual - expected);
  if (diff > delta) {
    throw new AssertionError(
      message || `Expected |${actual} - ${expected}| <= ${delta}, but difference is ${diff}`,
      actual,
      expected,
      'assertInDelta'
    );
  }
}

export function assertIncludes(collection, element, message) {
  let matched = false;
  if (typeof collection === 'string') {
    matched = collection.includes(element);
  } else if (Array.isArray(collection)) {
    matched = collection.includes(element) || collection.some(item => isDeepStrictEqual(item, element));
  } else if (collection instanceof Set || collection instanceof Map) {
    matched = collection.has(element);
  } else if (collection && typeof collection === 'object') {
    matched = Object.prototype.hasOwnProperty.call(collection, element);
  }
  if (!matched) {
    throw new AssertionError(
      message || `Expected collection to include ${formatValue(element)}`,
      collection,
      element,
      'assertIncludes'
    );
  }
}

export function assertDefined(value, message) {
  if (value === undefined || value === null) {
    throw new AssertionError(
      message || `Expected value to be defined and non-null, but got ${formatValue(value)}`,
      value,
      'defined',
      'assertDefined'
    );
  }
}

export function assertNull(value, message) {
  if (value !== null) {
    throw new AssertionError(
      message || `Expected null, but got ${formatValue(value)}`,
      value,
      null,
      'assertNull'
    );
  }
}

// --- Test Registration & Lifecycle Engine ------------------------------------

class SuiteNode {
  constructor(name, parent = null, options = {}) {
    this.name = name;
    this.parent = parent;
    this.options = options;
    this.tests = [];
    this.beforeEachHooks = [];
    this.afterEachHooks = [];
    this.beforeAllHooks = [];
    this.afterAllHooks = [];
  }
}

class TestRegistry {
  constructor() {
    this.rootSuites = [];
    this.activeSuite = null;
  }

  reset() {
    this.rootSuites = [];
    this.activeSuite = null;
  }

  suite(name, fn, options = {}) {
    const node = new SuiteNode(name, this.activeSuite, options);
    if (this.activeSuite) {
      this.activeSuite.tests.push(node);
    } else {
      this.rootSuites.push(node);
    }

    const previousSuite = this.activeSuite;
    this.activeSuite = node;
    try {
      fn();
    } finally {
      this.activeSuite = previousSuite;
    }
  }

  test(name, fn, options = {}) {
    if (!this.activeSuite) {
      // Create an implicit root suite if none exists
      this.suite('General Tests', () => {});
      this.activeSuite = this.rootSuites[this.rootSuites.length - 1];
    }
    this.activeSuite.tests.push({
      type: 'test',
      name,
      fn,
      options,
      suite: this.activeSuite
    });
  }

  beforeEach(fn) {
    if (this.activeSuite) this.activeSuite.beforeEachHooks.push(fn);
  }

  afterEach(fn) {
    if (this.activeSuite) this.activeSuite.afterEachHooks.push(fn);
  }

  beforeAll(fn) {
    if (this.activeSuite) this.activeSuite.beforeAllHooks.push(fn);
  }

  afterAll(fn) {
    if (this.activeSuite) this.activeSuite.afterAllHooks.push(fn);
  }
}

export const registry = new TestRegistry();

export function suite(name, fn) {
  registry.suite(name, fn);
}

export function describe(name, fn) {
  registry.suite(name, fn);
}

export function test(name, fn, options) {
  registry.test(name, fn, options);
}

export function it(name, fn, options) {
  registry.test(name, fn, options);
}

test.skip = (name, fn, options = {}) => {
  registry.test(name, fn, { ...options, skip: true });
};

suite.skip = (name, fn, options = {}) => {
  registry.suite(name, fn, { ...options, skip: true });
};

test.only = (name, fn, options = {}) => {
  registry.test(name, fn, { ...options, only: true });
};

export function beforeEach(fn) {
  registry.beforeEach(fn);
}

export function afterEach(fn) {
  registry.afterEach(fn);
}

export function beforeAll(fn) {
  registry.beforeAll(fn);
}

export function afterAll(fn) {
  registry.afterAll(fn);
}

// --- Tier Definitions & Metadata ----------------------------------------------

export const TIERS = [
  {
    id: 1,
    name: 'Tier 1: Feature Coverage',
    file: 'tier1_features.test.mjs',
    threshold: 40,
    description: 'Functional tests covering F1-F8 in isolation (>=5 tests per group)'
  },
  {
    id: 2,
    name: 'Tier 2: Boundaries & Corners',
    file: 'tier2_boundaries.test.mjs',
    threshold: 40,
    description: 'Edge cases, 0-capacity, timeouts, TOTP rotation, empty states (>=5 per group)'
  },
  {
    id: 3,
    name: 'Tier 3: Pairwise Combinations',
    file: 'tier3_pairwise.test.mjs',
    threshold: 8,
    description: 'Cross-feature state interaction matrix across stages (>=8 pairwise tests)'
  },
  {
    id: 4,
    name: 'Tier 4: Real-World Scenarios',
    file: 'tier4_application.test.mjs',
    threshold: 5,
    description: 'End-to-end multi-step weekly cinema club lifecycle simulations (>=5 scenarios)'
  }
];

// --- Test Execution Engine ----------------------------------------------------

async function runWithTimeout(fn, timeoutMs) {
  let timerId;
  const timeoutPromise = new Promise((_, reject) => {
    timerId = setTimeout(() => {
      reject(new Error(`Test timed out after ${timeoutMs}ms`));
    }, timeoutMs);
  });

  try {
    return await Promise.race([Promise.resolve().then(() => fn()), timeoutPromise]);
  } finally {
    clearTimeout(timerId);
  }
}

function getLineFromStack(stack) {
  if (!stack) return '';
  const lines = stack.split('\n');
  for (const line of lines) {
    if (line.includes('.test.mjs:')) {
      const match = line.match(/\((.*?:\d+:\d+)\)/) || line.match(/at\s+(.*?:\d+:\d+)/);
      if (match) return match[1];
    }
  }
  return '';
}

async function executeSuite(suiteNode, stats, inheritedBeforeEach = [], inheritedAfterEach = []) {
  if (suiteNode.options?.skip) {
    console.log(`  ${colors.dim}${colors.yellow}○ Suite Skipped: ${suiteNode.name}${colors.reset}`);
    return;
  }

  console.log(`  ${colors.cyan}● ${colors.bold}${suiteNode.name}${colors.reset}`);

  // Execute beforeAll hooks
  for (const hook of suiteNode.beforeAllHooks) {
    await hook();
  }

  const currentBeforeEach = [...inheritedBeforeEach, ...suiteNode.beforeEachHooks];
  const currentAfterEach = [...suiteNode.afterEachHooks, ...inheritedAfterEach];

  for (const item of suiteNode.tests) {
    if (item.type === 'test') {
      const testItem = item;

      // Check grep filter
      if (options.grep && !options.grep.test(testItem.name) && !options.grep.test(suiteNode.name)) {
        continue;
      }

      // Check skip
      if (testItem.options?.skip) {
        stats.skipped++;
        console.log(`    ${colors.yellow}○ ${testItem.name} ${colors.dim}(skipped)${colors.reset}`);
        continue;
      }

      // Execute beforeEach hooks
      let hookFailed = false;
      for (const hook of currentBeforeEach) {
        try {
          await hook();
        } catch (err) {
          hookFailed = true;
          stats.failed++;
          stats.errors.push({
            suiteName: suiteNode.name,
            testName: testItem.name,
            error: new Error(`beforeEach hook failed: ${err.message}`)
          });
          console.log(`    ${colors.red}✗ ${testItem.name} ${colors.dim}[beforeEach failed]${colors.reset}`);
          break;
        }
      }

      if (hookFailed) {
        if (options.bail) throw new Error('Bailing after failure');
        continue;
      }

      // Execute Test Function
      const tStart = performance.now();
      try {
        await runWithTimeout(testItem.fn, options.timeout);
        const duration = (performance.now() - tStart).toFixed(1);
        stats.passed++;
        console.log(`    ${colors.green}✓${colors.reset} ${testItem.name} ${colors.dim}(${duration}ms)${colors.reset}`);
      } catch (err) {
        const duration = (performance.now() - tStart).toFixed(1);
        stats.failed++;
        stats.errors.push({
          suiteName: suiteNode.name,
          testName: testItem.name,
          error: err
        });
        console.log(`    ${colors.red}✗${colors.reset} ${colors.bold}${testItem.name}${colors.reset} ${colors.dim}(${duration}ms)${colors.reset}`);

        // Immediate failure diagnostic
        const loc = getLineFromStack(err.stack);
        console.log(`      ${colors.red}${err.name || 'Error'}: ${err.message}${colors.reset}`);
        if (loc) {
          console.log(`      ${colors.dim}at ${loc}${colors.reset}`);
        }

        if (options.bail) {
          throw new Error(`Bailing after failure in test: ${testItem.name}`);
        }
      }

      // Execute afterEach hooks
      for (const hook of currentAfterEach) {
        try {
          await hook();
        } catch (err) {
          console.log(`      ${colors.red}[afterEach hook error]: ${err.message}${colors.reset}`);
        }
      }
    } else if (item instanceof SuiteNode) {
      // Nested suite
      await executeSuite(item, stats, currentBeforeEach, currentAfterEach);
    }
  }

  // Execute afterAll hooks
  for (const hook of suiteNode.afterAllHooks) {
    try {
      await hook();
    } catch (err) {
      console.log(`    ${colors.red}[afterAll hook error]: ${err.message}${colors.reset}`);
    }
  }
}

// --- Tier Runner Coordinator --------------------------------------------------

export async function runTier(tierConfig, baseDir) {
  const filePath = path.resolve(baseDir, tierConfig.file);
  const tierStats = {
    id: tierConfig.id,
    name: tierConfig.name,
    file: tierConfig.file,
    threshold: tierConfig.threshold,
    passed: 0,
    failed: 0,
    skipped: 0,
    durationMs: 0,
    errors: []
  };

  console.log(`\n${colors.gold}${colors.bold}▶ ${tierConfig.name.toUpperCase()}${colors.reset} ${colors.dim}(${tierConfig.file})${colors.reset}`);
  console.log(`${colors.dim}  Description: ${tierConfig.description}${colors.reset}`);

  if (!fs.existsSync(filePath)) {
    tierStats.failed = 1;
    tierStats.errors.push({
      suiteName: tierConfig.name,
      testName: 'File existence',
      error: new Error(`Test file not found: ${filePath}`)
    });
    console.log(`  ${colors.red}✗ Test file missing: ${tierConfig.file}${colors.reset}`);
    return tierStats;
  }

  registry.reset();
  const startTime = performance.now();

  try {
    // Dynamically import test suite file
    const fileUrl = pathToFileURL(filePath).href;
    await import(fileUrl);

    // Execute all registered suites in this tier
    for (const suiteNode of registry.rootSuites) {
      await executeSuite(suiteNode, tierStats);
    }
  } catch (err) {
    tierStats.failed++;
    tierStats.errors.push({
      suiteName: tierConfig.name,
      testName: 'Execution/Import',
      error: err
    });
    console.log(`  ${colors.red}✗ Tier execution interrupted: ${err.message}${colors.reset}`);
    if (err.stack && options.verbose) {
      console.log(err.stack);
    }
  }

  tierStats.durationMs = performance.now() - startTime;

  // Print Tier Summary
  const thresholdPassed = tierStats.passed >= tierConfig.threshold;
  const thresholdStatus = thresholdPassed
    ? `${colors.green}PASS (>=${tierConfig.threshold})${colors.reset}`
    : `${colors.red}THRESHOLD VIOLATION (${tierStats.passed} < ${tierConfig.threshold})${colors.reset}`;

  console.log(
    `  ${colors.bold}${tierConfig.name} Summary:${colors.reset} ` +
    `${colors.green}${tierStats.passed} passed${colors.reset}, ` +
    `${tierStats.failed > 0 ? colors.red : colors.dim}${tierStats.failed} failed${colors.reset}, ` +
    `${colors.dim}${tierStats.skipped} skipped${colors.reset} ` +
    `${colors.dim}(${tierStats.durationMs.toFixed(1)}ms)${colors.reset} [${thresholdStatus}]`
  );

  return tierStats;
}

// --- Main Orchestrator --------------------------------------------------------

export async function runAllTiers(baseDir = process.cwd()) {
  const globalStart = performance.now();

  console.log(`\n${colors.gold}${colors.bold}================================================================================${colors.reset}`);
  console.log(`${colors.gold}${colors.bold}  CU CINEMA CLUB E2E TEST RUNNER — REDESIGN & UX/UI OVERHAUL${colors.reset}`);
  console.log(`${colors.gold}${colors.bold}================================================================================${colors.reset}`);
  console.log(`${colors.dim}  Node: ${process.version} | Target: 4 Tiers (T1-T4) | Threshold: >=93 Tests${colors.reset}`);

  const activeTiers = options.tierFilter
    ? TIERS.filter(t => t.id === options.tierFilter)
    : TIERS;

  if (activeTiers.length === 0) {
    console.log(`${colors.red}No tiers matching filter --tier=${options.tierFilter}${colors.reset}`);
    process.exit(1);
  }

  const results = [];
  let bailed = false;

  for (const tierConfig of activeTiers) {
    try {
      const stats = await runTier(tierConfig, baseDir);
      results.push(stats);
      if (options.bail && stats.failed > 0) {
        bailed = true;
        break;
      }
    } catch (err) {
      console.log(`${colors.red}Fatal tier error: ${err.message}${colors.reset}`);
      bailed = true;
      break;
    }
  }

  const globalDuration = performance.now() - globalStart;

  // Summary Table Rendering
  console.log(`\n${colors.bold}================================================================================${colors.reset}`);
  console.log(`${colors.bold}  FINAL TEST EXECUTION SUMMARY${colors.reset}`);
  console.log(`${colors.bold}================================================================================${colors.reset}`);
  console.log(`  ${'Tier'.padEnd(34)} ${'Passed'.padStart(8)} ${'Failed'.padStart(8)} ${'Skipped'.padStart(8)} ${'Target'.padStart(8)}   ${'Status'}`);
  console.log(`  ${'-'.repeat(76)}`);

  let totalPassed = 0;
  let totalFailed = 0;
  let totalSkipped = 0;
  let totalThreshold = 0;
  let allThresholdsMet = true;

  for (const res of results) {
    totalPassed += res.passed;
    totalFailed += res.failed;
    totalSkipped += res.skipped;
    totalThreshold += res.threshold;

    const tierThresholdMet = res.passed >= res.threshold;
    if (!tierThresholdMet) allThresholdsMet = false;

    const statusStr = (res.failed === 0 && tierThresholdMet)
      ? `${colors.green}PASS${colors.reset}`
      : `${colors.red}FAIL${colors.reset}`;

    console.log(
      `  ${res.name.padEnd(34)} ` +
      `${String(res.passed).padStart(8)} ` +
      `${String(res.failed).padStart(8)} ` +
      `${String(res.skipped).padStart(8)} ` +
      `${('≥' + res.threshold).padStart(8)}   ` +
      `${statusStr}`
    );
  }

  console.log(`  ${'-'.repeat(76)}`);
  const grandStatus = (totalFailed === 0 && allThresholdsMet && !bailed)
    ? `${colors.bold}${colors.green}PASS${colors.reset}`
    : `${colors.bold}${colors.red}FAIL${colors.reset}`;

  console.log(
    `  ${'TOTAL'.padEnd(34)} ` +
    `${String(totalPassed).padStart(8)} ` +
    `${String(totalFailed).padStart(8)} ` +
    `${String(totalSkipped).padStart(8)} ` +
    `${('≥' + totalThreshold).padStart(8)}   ` +
    `${grandStatus}`
  );
  console.log(`${colors.bold}================================================================================${colors.reset}`);

  // Summary Diagnostics
  console.log(`  Total Duration: ${globalDuration.toFixed(1)} ms`);
  console.log(`  Tests:          ${totalPassed} passed, ${totalFailed} failed, ${totalSkipped} skipped`);

  if (!allThresholdsMet) {
    console.log(`  ${colors.red}${colors.bold}THRESHOLD VIOLATION: One or more tiers did not satisfy required test counts!${colors.reset}`);
  }

  // Error Details Dump
  const allErrors = results.flatMap(r => r.errors);
  if (allErrors.length > 0) {
    console.log(`\n${colors.red}${colors.bold}Failures (${allErrors.length}):${colors.reset}`);
    allErrors.forEach((e, idx) => {
      console.log(`\n  ${idx + 1}) [${e.suiteName}] ${e.testName}:`);
      console.log(`     ${colors.red}${e.error.stack || e.error.message}${colors.reset}`);
    });
  }

  const success = totalFailed === 0 && allThresholdsMet && !bailed;
  console.log(`\n  Execution Result: ${success ? colors.green + colors.bold + 'SUCCESS (All Tiers Passed)' : colors.red + colors.bold + 'FAILURE'} ${colors.reset}\n`);

  return success ? 0 : 1;
}

// --- CLI & Direct Invocation Handler -----------------------------------------

const isMainModule = process.argv[1] && (
  fileURLToPath(import.meta.url) === process.argv[1] ||
  path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)
);

let directRunExecuted = false;

if (isMainModule) {
  const baseDir = path.dirname(fileURLToPath(import.meta.url));
  runAllTiers(baseDir).then(exitCode => {
    process.exit(exitCode);
  }).catch(err => {
    console.error('Fatal unhandled runner error:', err);
    process.exit(1);
  });
} else {
  // Support running individual test files directly (e.g. `node e2e_tests/tier1_features.test.mjs`)
  process.on('beforeExit', async (code) => {
    if (code !== 0 || directRunExecuted) return;
    if (registry.rootSuites.length > 0) {
      directRunExecuted = true;
      console.log(`\n${colors.gold}${colors.bold}▶ DIRECT TEST FILE EXECUTION: ${path.basename(process.argv[1])}${colors.reset}\n`);
      const directStats = { passed: 0, failed: 0, skipped: 0, errors: [] };
      const startTime = performance.now();
      for (const suiteNode of registry.rootSuites) {
        await executeSuite(suiteNode, directStats);
      }
      const duration = (performance.now() - startTime).toFixed(1);
      console.log(`\n${colors.bold}Execution Summary:${colors.reset} ${colors.green}${directStats.passed} passed${colors.reset}, ${directStats.failed > 0 ? colors.red : colors.dim}${directStats.failed} failed${colors.reset}, ${colors.dim}${directStats.skipped} skipped${colors.reset} (${duration}ms)\n`);
      process.exit(directStats.failed > 0 ? 1 : 0);
    }
  });
}
