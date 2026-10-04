const fs=require('fs');
const buf=fs.readFileSync(process.argv[2]);
const len=buf.readUInt32LE(12);
const json=JSON.parse(buf.slice(20,20+len).toString('utf8'));
console.log('materials:', (json.materials||[]).map(m=>m.name).join(' '));
console.log('nodes:', (json.nodes||[]).map(n=>n.name).join(' '));
console.log('extensionsRequired:', (json.extensionsRequired||[]).join(' '));
