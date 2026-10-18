import { test, expect } from '@playwright/test';

test('upload preview, progress and structured fields on desktop and mobile', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }));
  const job = { id: 'test-job', status: 'queued', filename: 'sample.txt' };
  const completed = {
    ...job, status: 'complete', seconds: 2, source_url: '/api/extractions/test-job/original',
    profile: {
      personal_information: { full_name: 'JESSICA CLAIRE', emails: ['jessica@example.test'] },
      skills: [{ raw_name: 'Python' }], work_experience: [], education: [], projects: [],
      certifications: [], languages: [], awards: [], summary: null,
      extraction_warnings: ['Rejected personal_information.location: not_supported_by_reader_text']
    },
  };
  await page.route('**/api/extractions', route => route.fulfill(
    route.request().method() === 'GET' ? { json: [completed] } : { status: 202, json: job }
  ));
  await page.route('**/api/extractions/test-job', route => route.fulfill({ json: completed }));
  await page.route('**/api/extractions/test-job/original', route => route.fulfill({ body: 'JESSICA CLAIRE\nPython developer' }));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'New extraction' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Main navigation' })).toBeVisible();
  await page.locator('input[type=file]').setInputFiles({ name: 'sample.txt', mimeType: 'text/plain', buffer: Buffer.from('JESSICA CLAIRE\nPython developer') });
  await expect(page.locator('pre')).toContainText('Python developer');
  await page.getByRole('button', { name: 'Extract information' }).click();
  await expect(page.locator('.results')).toContainText('JESSICA CLAIRE');
  await expect(page.locator('.results')).toContainText('jessica@example.test');
  await expect(page.getByRole('button', { name: 'Export JSON' })).toBeVisible();
  const download = page.waitForEvent('download');
  await page.getByRole('button', { name: 'Export JSON' }).click();
  expect((await download).suggestedFilename()).toBe('sample.json');
  await expect(page.locator('.results .record')).toHaveCount(0);
  await expect(page.getByText('CV Management', { exact: true })).toBeVisible();
  await expect(page.getByText('Source-check warnings', { exact: false })).toHaveCount(0);
  await expect(page.locator('.progress')).toHaveCount(0);
  await page.getByRole('button', { name: /Files/ }).click();
  await expect(page.getByRole('heading', { name: 'Files and results' })).toBeVisible();
  await expect(page.locator('.file-row')).toContainText('sample.txt');
  await page.locator('.file-row').click();
  await expect(page.locator('.results')).toContainText('JESSICA CLAIRE');
  await page.locator('.results').evaluate(element => element.scrollTop = 0);
  await page.screenshot({ path: 'test-results/desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole('heading', { name: 'Extracted information' })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/mobile.png', fullPage: true });
  expect(errors).toEqual([]);
});

function samplePdf() {
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    '<< /Type /Pages /Kids [3 0 R 4 0 R] /Count 2 >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
    '<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources << /Font << /F1 5 0 R >> >> /Contents 6 0 R >>',
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ];
  const stream = 'BT /F1 22 Tf 40 760 Td (CV preview test) Tj ET';
  objects.push(`<< /Length ${stream.length} >>\nstream\n${stream}\nendstream`);
  let pdf = '%PDF-1.4\n';
  const offsets = [0];
  objects.forEach((object, i) => { offsets.push(Buffer.byteLength(pdf)); pdf += `${i + 1} 0 obj\n${object}\nendobj\n`; });
  const xref = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets.slice(1).map(offset => `${String(offset).padStart(10, '0')} 00000 n \n`).join('');
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xref}\n%%EOF`;
  return Buffer.from(pdf);
}

test('PDF fills the pane as pages without native viewer controls', async ({ page }) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.route('**/api/health', route => route.fulfill({ json: { status: 'ok' } }));
  await page.route('**/api/extractions', route => route.fulfill({ json: [] }));
  await page.goto('/');
  await page.locator('input[type=file]').setInputFiles({ name: 'preview.pdf', mimeType: 'application/pdf', buffer: samplePdf() });
  await expect(page.locator('canvas.pdf-page')).toHaveCount(2);
  await expect.poll(() => page.locator('canvas').first().evaluate(c => c.width)).toBeGreaterThan(300);
  await expect.poll(() => page.locator('canvas').first().evaluate(c => {
    const data = c.getContext('2d').getImageData(0, 0, c.width, c.height).data;
    return data.some((v, i) => i % 4 !== 3 && v < 200);
  })).toBe(true);
  await expect(page.locator('iframe, embed, object, [role=toolbar]')).toHaveCount(0);
  const pane = await page.locator('.document').boundingBox();
  const canvas = await page.locator('canvas').first().boundingBox();
  expect(Math.abs(pane.width - canvas.width)).toBeLessThan(20);
  await page.screenshot({ path: 'test-results/pdf-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect.poll(() => page.locator('canvas').first().evaluate(c => Math.abs(c.clientHeight / c.clientWidth - 842 / 595))).toBeLessThan(0.02);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/pdf-mobile.png', fullPage: true });
  await page.locator('input[type=file]').setInputFiles({ name: 'broken.pdf', mimeType: 'application/pdf', buffer: Buffer.from('not a pdf') });
  await expect(page.getByRole('alert')).toContainText('invalid structure');
  expect(errors).toEqual([]);
});
