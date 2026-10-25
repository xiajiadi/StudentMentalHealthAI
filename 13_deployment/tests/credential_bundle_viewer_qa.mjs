import assert from 'node:assert/strict';
import { randomBytes, webcrypto } from 'node:crypto';
import fs from 'node:fs/promises';
import path from 'node:path';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';

const DEPLOYMENT_DIR = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const FRONTEND_DIR = path.resolve(DEPLOYMENT_DIR, '../10_frontend');
const require = createRequire(pathToFileURL(path.join(FRONTEND_DIR, 'package.json')));
const { chromium } = require('@playwright/test');

async function encryptedFixture(passphrase) {
  const salt = randomBytes(16);
  const iv = randomBytes(12);
  const material = await webcrypto.subtle.importKey(
    'raw', new TextEncoder().encode(passphrase), 'PBKDF2', false, ['deriveKey'],
  );
  const key = await webcrypto.subtle.deriveKey(
    { name: 'PBKDF2', salt, iterations: 310000, hash: 'SHA-256' },
    material,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt'],
  );
  const payload = JSON.stringify({
    created_at: '2026-10-25T00:00:00.000Z',
    credentials: [{
      user_id: 'USER_SYNTHETIC_TEST',
      role: 'teacher',
      login_name: 'SYNTHETIC_TEST_USER',
      display_name: '合成测试账号',
      credential: 'synthetic-one-time-token',
      expires_at: '2026-10-25T01:00:00.000Z',
    }],
  });
  const ciphertext = await webcrypto.subtle.encrypt(
    { name: 'AES-GCM', iv }, key, new TextEncoder().encode(payload),
  );
  return Buffer.from(JSON.stringify({
    format: 'psynova-credentials-encrypted-v1',
    algorithm: 'AES-256-GCM',
    kdf: 'PBKDF2-SHA-256',
    iterations: 310000,
    salt: salt.toString('base64'),
    iv: iv.toString('base64'),
    ciphertext: Buffer.from(ciphertext).toString('base64'),
  }));
}

async function main() {
  const viewerPath = path.join(DEPLOYMENT_DIR, 'credential_bundle_viewer.html');
  const html = await fs.readFile(viewerPath, 'utf8');
  assert.match(html, /Content-Security-Policy/);
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.PSYNOVA_TEST_CHROMIUM ? { executablePath: process.env.PSYNOVA_TEST_CHROMIUM } : {}),
  });
  try {
    const page = await browser.newPage();
    const requests = [];
    page.on('request', (request) => requests.push(request.url()));
    await page.goto(pathToFileURL(viewerPath).href);
    const fixture = await encryptedFixture('synthetic-viewer-passphrase');
    await page.locator('#file').setInputFiles({
      name: 'synthetic-encrypted-credentials.json',
      mimeType: 'application/json',
      buffer: fixture,
    });
    await page.locator('#passphrase').fill('synthetic-viewer-passphrase');
    await page.locator('#decrypt').click();
    await page.getByText('已在本机解密 1 条凭据。').waitFor();
    assert.equal(await page.getByText('SYNTHETIC_TEST_USER').count(), 1);
    assert.equal(await page.locator('.token').inputValue(), 'synthetic-one-time-token');
    assert.equal(await page.locator('.token').getAttribute('type'), 'password');
    await page.locator('#toggle').click();
    assert.equal(await page.locator('.token').getAttribute('type'), 'text');
    assert.deepEqual(requests.filter((url) => /^https?:/i.test(url)), []);

    await page.locator('#clear').click();
    assert.equal(await page.locator('#results').textContent(), '');
    assert.equal(await page.locator('#passphrase').inputValue(), '');
    console.log(JSON.stringify({ status: 'PASS', records: 1, network_requests: 0 }));
  } finally {
    await browser.close();
  }
}

main().catch(() => {
  console.log(JSON.stringify({ status: 'FAIL', error_code: 'credential_viewer_qa_failed' }));
  process.exitCode = 1;
});
