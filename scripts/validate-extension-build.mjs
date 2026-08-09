#!/usr/bin/env node

/**
 * Validates generated WXT extension builds.
 *
 * Usage:
 *   node scripts/validate-extension-build.mjs [chrome|firefox]
 *
 * Reads the generated manifest.json and checks that every referenced file
 * actually exists in the output directory.
 */

import { readFileSync, existsSync, readdirSync } from 'fs';
import { join, resolve } from 'path';

const EXTENSION_DIR = resolve(import.meta.dirname ?? '.', '..', 'apps', 'extension');

const targets = process.argv.slice(2);
const browsers = targets.length > 0
  ? targets
  : ['chrome-mv3', 'firefox-mv3'];

let exitCode = 0;

for (const browser of browsers) {
  console.log(`\n══════════════════════════════════════════`);
  console.log(`  Validating: ${browser}`);
  console.log(`══════════════════════════════════════════\n`);

  const outputDir = join(EXTENSION_DIR, '.output', browser);

  if (!existsSync(outputDir)) {
    console.error(`  ❌ Output directory does not exist: ${outputDir}`);
    console.error(`     Run: pnpm --filter @barq/extension build`);
    exitCode = 1;
    continue;
  }

  const manifestPath = join(outputDir, 'manifest.json');
  if (!existsSync(manifestPath)) {
    console.error(`  ❌ manifest.json not found in: ${outputDir}`);
    exitCode = 1;
    continue;
  }

  const manifest = JSON.parse(readFileSync(manifestPath, 'utf-8'));
  console.log(`  ✅ manifest.json found`);

  // Validate manifest_version
  if (manifest.manifest_version !== 3) {
    console.error(`  ❌ manifest_version is ${manifest.manifest_version}, expected 3`);
    exitCode = 1;
  } else {
    console.log(`  ✅ manifest_version: 3`);
  }

  // Validate name and version
  if (!manifest.name) {
    console.error(`  ❌ Missing 'name' field`);
    exitCode = 1;
  } else {
    console.log(`  ✅ name: ${manifest.name}`);
  }

  if (!manifest.version) {
    console.error(`  ❌ Missing 'version' field`);
    exitCode = 1;
  } else {
    console.log(`  ✅ version: ${manifest.version}`);
  }

  // Validate background
  const bg = manifest.background;
  if (bg) {
    const bgFile = bg.service_worker || (bg.scripts && bg.scripts[0]);
    if (bgFile) {
      const bgPath = join(outputDir, bgFile);
      if (existsSync(bgPath)) {
        console.log(`  ✅ background: ${bgFile}`);
      } else {
        console.error(`  ❌ background file missing: ${bgFile}`);
        console.error(`     Expected at: ${bgPath}`);
        exitCode = 1;
      }
    } else {
      console.error(`  ❌ background has no service_worker or scripts`);
      exitCode = 1;
    }
  } else {
    console.error(`  ❌ No 'background' field in manifest`);
    exitCode = 1;
  }

  // Validate popup
  const popup = manifest.action?.default_popup;
  if (popup) {
    const popupPath = join(outputDir, popup);
    if (existsSync(popupPath)) {
      console.log(`  ✅ popup: ${popup}`);
    } else {
      console.error(`  ❌ popup file missing: ${popup}`);
      console.error(`     Expected at: ${popupPath}`);
      exitCode = 1;
    }
  } else {
    console.warn(`  ⚠️  No default_popup in action (may be intentional)`);
  }

  // Validate icons
  const icons = manifest.icons;
  if (icons && typeof icons === 'object') {
    for (const [size, iconPath] of Object.entries(icons)) {
      const fullPath = join(outputDir, iconPath);
      if (existsSync(fullPath)) {
        console.log(`  ✅ icon ${size}: ${iconPath}`);
      } else {
        console.error(`  ❌ icon ${size} missing: ${iconPath}`);
        console.error(`     Expected at: ${fullPath}`);
        exitCode = 1;
      }
    }
  } else {
    console.warn(`  ⚠️  No icons declared in manifest`);
  }

  // Validate action icons
  const actionIcons = manifest.action?.default_icon;
  if (actionIcons && typeof actionIcons === 'object') {
    for (const [size, iconPath] of Object.entries(actionIcons)) {
      const fullPath = join(outputDir, iconPath);
      if (existsSync(fullPath)) {
        console.log(`  ✅ action icon ${size}: ${iconPath}`);
      } else {
        console.error(`  ❌ action icon ${size} missing: ${iconPath}`);
        exitCode = 1;
      }
    }
  }

  // Validate content_scripts
  const contentScripts = manifest.content_scripts;
  if (contentScripts && Array.isArray(contentScripts)) {
    for (const cs of contentScripts) {
      for (const jsFile of (cs.js || [])) {
        const jsPath = join(outputDir, jsFile);
        if (!existsSync(jsPath)) {
          console.error(`  ❌ content script missing: ${jsFile}`);
          exitCode = 1;
        }
      }
      for (const cssFile of (cs.css || [])) {
        const cssPath = join(outputDir, cssFile);
        if (!existsSync(cssPath)) {
          console.error(`  ❌ content script CSS missing: ${cssFile}`);
          exitCode = 1;
        }
      }
    }
  }

  // Validate web_accessible_resources
  const war = manifest.web_accessible_resources;
  if (war && Array.isArray(war)) {
    for (const entry of war) {
      const resources = entry.resources || (typeof entry === 'string' ? [entry] : []);
      for (const resource of resources) {
        // Skip glob patterns
        if (resource.includes('*')) continue;
        const resourcePath = join(outputDir, resource);
        if (!existsSync(resourcePath)) {
          console.warn(`  ⚠️  web_accessible_resource not found: ${resource}`);
        }
      }
    }
  }

  // Check for prohibited patterns
  const manifestText = readFileSync(manifestPath, 'utf-8');
  const prohibited = [
    { pattern: 'entrypoints/', label: 'source-tree path "entrypoints/"' },
    { pattern: '.ts"', label: 'TypeScript file reference (.ts)' },
    { pattern: '.tsx"', label: 'TSX file reference (.tsx)' },
  ];
  for (const { pattern, label } of prohibited) {
    if (manifestText.includes(pattern)) {
      console.error(`  ❌ Manifest contains prohibited ${label}`);
      exitCode = 1;
    }
  }

  // Firefox-specific validation
  if (browser.includes('firefox')) {
    const gecko = manifest.browser_specific_settings?.gecko;
    if (gecko) {
      console.log(`  ✅ Firefox gecko.id: ${gecko.id}`);
      console.log(`  ✅ Firefox strict_min_version: ${gecko.strict_min_version}`);
    } else {
      console.warn(`  ⚠️  No browser_specific_settings.gecko for Firefox build`);
    }
  }

  // Summary
  console.log(`\n  Output directory: ${outputDir}`);
  const allFiles = listFilesRecursively(outputDir);
  console.log(`  Total files: ${allFiles.length}`);
}

if (exitCode === 0) {
  console.log(`\n✅ All extension builds validated successfully.\n`);
} else {
  console.error(`\n❌ Extension build validation FAILED.\n`);
}

process.exit(exitCode);

function listFilesRecursively(dir) {
  const entries = readdirSync(dir, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const fullPath = join(dir, entry.name);
    if (entry.isDirectory()) {
      files.push(...listFilesRecursively(fullPath));
    } else {
      files.push(fullPath);
    }
  }
  return files;
}
