import { NodeIO } from '@gltf-transform/core';
const io = new NodeIO();
const doc = await io.read(process.argv[2]);
doc.getRoot().listMaterials().forEach(m => console.log(JSON.stringify(m.getName()), m.getBaseColorFactor().map(n=>n.toFixed(2)).join(',')));
