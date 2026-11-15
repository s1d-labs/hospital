import { chromium } from 'playwright-core';
import { mkdtemp, mkdir, writeFile, rename } from 'node:fs/promises';
import path from 'node:path';
import { doctor, hospital } from './fields.mjs';

const options = {
  hospitals: { route: 'facility', endpoint: '/v4/hfr/facility/search/searchFacility', project: hospital,
    filters: [['Search By', 'Facility Type'], ['Facility Type', 'Hospital']] },
  facility: { route:'facility', endpoint:'/v4/hfr/facility/search/searchFacility', project:hospital,
    filters:[['Search By','Facility ID']] },
  doctors: { route: 'healthcareProfessional', endpoint: '/v4/hpr/search/hprProfileSearch', project: doctor,
    filters: [['Health Professional', 'Doctor']] }
};
const kind = process.argv[2];
const config = options[kind];
if (!Object.hasOwn(options, kind)) throw new Error('Choose hospitals, doctors, or facility <HFR ID>');

const requestedId = process.argv[3];
if (kind === 'facility' && !/^IN[0-9]{10}$/.test(requestedId ?? '')) throw new Error('Supply the exact HFR facility ID');
const root = path.resolve('exports');
await mkdir(root, {recursive:true, mode:0o700});
const folder = await mkdtemp(path.join(root, kind + '-'));
const browser = await chromium.launch({channel:'chrome', headless:false});
const page = await browser.newPage();
const seen = new Set();
let sequence = 0;
let queue = Promise.resolve();
const fields = Object.keys(config.project({}));
const line = cells => cells.map(v => '"' + String(v).replaceAll('"','""') + '"').join(',') + '\r\n';
async function save(payload) {
  const data = Array.isArray(payload?.content) ? payload : payload?.data;
  if (!Array.isArray(data?.content)) throw new Error('No result list in response. Check the search form.');
  const fresh = new Map();
  for (const record of data.content) {
    const row = config.project(record);
    const id = row[fields[0]];
    if (!id || !row[fields[1]]) throw new Error('Missing registry ID or name');
    if (kind === 'facility' && id !== requestedId) continue;
    if (kind === 'hospitals' && row.facility_type.toLowerCase() !== 'hospital') continue;
    if (!seen.has(id)) fresh.set(id,row);
  }
  if (fresh.size) {
    const filename = path.join(folder,'page-' + String(++sequence).padStart(5,'0') + '.csv');
    const csv = line(fields) + Array.from(fresh.values(),row => line(fields.map(k => row[k]))).join('');
    await writeFile(filename + '.tmp',csv,{mode:0o600});
    await rename(filename + '.tmp',filename);
    for (const id of fresh.keys()) seen.add(id);
  }
  console.log('Saved ' + fresh.size + ' new rows, ' + seen.size + ' total in ' + folder);
}
page.on('response', response => {
  const url = new URL(response.url());
  if (response.request().method() !== 'POST' || url.origin !== 'https://apinhpr.abdm.gov.in' ||
      url.pathname !== config.endpoint || !response.ok()) return;
  const body = response.json().then(payload => ({payload}), error => ({error}));
  queue = queue.then(async () => {
    const {payload,error} = await body;
    if (error) throw error;
    await save(payload);
  }).catch(error => {process.exitCode = 1; console.error('Page not saved:',error.message);});
});
try {
  await page.goto('https://nhpr.abdm.gov.in/nhpr/v4/search/' + config.route, {waitUntil:'domcontentloaded'});
  for (const [field,value] of config.filters) {
    const input = page.getByText(field,{exact:true}).locator('..').getByRole('combobox');
    await input.fill(value);
    await page.getByRole('option',{name:value,exact:true}).click();
  }
  if (kind === 'facility') await page.locator('input[name="searchInput"]').fill(requestedId);
  console.log('Choose the geography, enter the CAPTCHA and click Search. Use Load More for further pages. Close the window when saving is complete.');
  if (!page.isClosed()) await page.waitForEvent('close',{timeout:0});
} finally {
  await queue;
  await browser.close();
}
