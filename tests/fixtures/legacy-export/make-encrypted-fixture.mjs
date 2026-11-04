// Writes encrypted.json: a small bundle encrypted exactly as the old MetaList's Backup does
// (MetaList_old/js/model/persist.js saveToFileSystemEncryptedJson), by its own encryptText.
// The tests read it as an export and, rows in a database, as the old MetaList's own file.
//
//   node tests/fixtures/legacy-export/make-encrypted-fixture.mjs ~/Desktop/MetaList_old/js/utils/crypto.js PASSWORD
import fs from 'node:fs';

const [cryptoPath, password] = process.argv.slice(2);
if (!cryptoPath || !password) throw new Error('usage: make-encrypted-fixture.mjs <MetaList_old crypto.js> <password>');
const encryptText = new Function(`${fs.readFileSync(cryptoPath, 'utf8')}; return encryptText;`)();
const bufferToHex = buffer => [...new Uint8Array(buffer)].map(byte => byte.toString(16).padStart(2, '0')).join('');
const items = [
  {id: 1, prev: null, next: 2, creation: 1700000000000, last_edit: 1700000001000,
   subitems: [{indent: 0, data: 'Bank login', tags: 'finance', collapse: false},
              {indent: 1, data: 'hunter2 — pässwörd ✓', tags: '@password', collapse: false}]},
  {id: 2, prev: 1, next: null, creation: 1700000002000, last_edit: 1700000003000,
   subitems: [{indent: 0, data: 'Groceries', tags: 'todo', collapse: false}]},
];
const data = [];
for (const item of items) {
  const encrypted = await encryptText(JSON.stringify(item.subitems), password);
  const encryptedItem = structuredClone(item);
  delete encryptedItem.subitems;
  encryptedItem.iv = encrypted.iv;
  encryptedItem.subitems_enc = bufferToHex(encrypted.encBuffer);
  data.push(encryptedItem);
}
const bundle = {data_schema_version: 23, encryption: {encrypted: true, encryption_scheme_version: 1, digest: 'SHA-256', alg: 'AES-GCM'}, data};
fs.writeFileSync(new URL('./encrypted.json', import.meta.url), `${JSON.stringify(bundle, undefined, 4)}\n`);
