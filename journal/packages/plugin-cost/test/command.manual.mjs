/** Ad-hoc check: the generated host reports a real session. */
import { costReport, name, inject, apply } from '../lib/index.js';

const cwd = process.argv[2] ?? process.cwd();
const sid = process.argv[3] ?? 'd772db00-c884-48e1-acf2-cb95cad2992d';
const arg = process.argv[4] ?? '4';

console.log(`plugin: name=${name} inject=${JSON.stringify(inject)} apply=${typeof apply}`);
console.log(`cwd=${cwd}`);
console.log('');
console.log(costReport(sid, cwd, arg));
console.log('');
console.log('--- bad argument falls back to usage ---');
console.log(costReport(sid, cwd, 'nonsense').split('\n')[0]);
console.log('--- an unknown session refuses instead of guessing ---');
console.log(costReport('does-not-exist', cwd, '').split('\n')[0]);
console.log('--- a wrong cwd refuses instead of guessing ---');
console.log(costReport(sid, 'C:\\definitely-not-here', '').split('\n')[0]);
