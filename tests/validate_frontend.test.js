import { test, describe } from 'node:test';
import assert from 'node:assert';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const __dirname = dirname(fileURLToPath(import.meta.url));
const PROJECT_ROOT = join(__dirname, '..');
const LESSONS_DIR = join(PROJECT_ROOT, 'lessons');
const APP_JS_PATH = join(PROJECT_ROOT, 'app.js');

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

describe('Why Academy Frontend Validator', () => {
    test('All simulation types in lessons are implemented in app.js', () => {
        const lessonFiles = walkDir(LESSONS_DIR);
        const appJsContent = readFileSync(APP_JS_PATH, 'utf8');
        
        const missingTypes = new Set();

        lessonFiles.forEach((file) => {
            const rawData = JSON.parse(readFileSync(file, 'utf8'));
            if (rawData.blocks) {
                rawData.blocks.forEach(block => {
                    if (block.simulation_config && block.simulation_config.type) {
                        const simType = block.simulation_config.type;
                        
                        // Check if the simulation type exists as a string literal in app.js
                        const exists = appJsContent.includes(`'${simType}'`) || appJsContent.includes(`"${simType}"`) || appJsContent.includes(`\`${simType}\``);
                        
                        if (!exists) {
                            missingTypes.add(simType);
                        }
                    }
                });
            }
        });

        const missingArr = Array.from(missingTypes);
        if (missingArr.length > 0) {
            assert.fail(`Missing simulation types in app.js: ${missingArr.join(', ')}. Please implement rendering logic for these in app.js.`);
        } else {
            assert.ok(true);
        }
    });
});
