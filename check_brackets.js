const fs = require('fs');
const code = fs.readFileSync('C:\\Users\\1\\Documents\\销售客服智能体\\static\\solda.js', 'utf8');
let braces = 0, brackets = 0, parens = 0;
for (const c of code) {
  if (c === '{') braces++;
  if (c === '}') braces--;
  if (c === '[') brackets++;
  if (c === ']') brackets--;
  if (c === '(') parens++;
  if (c === ')') parens--;
}
console.log('Braces:', braces, 'Brackets:', brackets, 'Parens:', parens);
if (braces === 0 && brackets === 0 && parens === 0) console.log('solda.js bracket balance OK');
else console.log('WARNING: bracket imbalance detected');
