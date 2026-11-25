import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import test from 'node:test';

test('hosted Streamlit test app exports a valid Moodle GIFT file and protects the teacher page', {timeout:80000}, async t=>{
  const url=process.env.VOCAB_STAGE_STREAMLIT;
  assert.equal(url,'https://vocabresearch-integration.streamlit.app');
  const {chromium}=await import(process.env.VOCAB_PLAYWRIGHT_ENTRY||'playwright-core');
  const browser=await chromium.launch({headless:true,executablePath:process.env.VOCAB_E2E_CHROME});
  t.after(()=>browser.close());
  const page=await browser.newPage();
  await page.goto(url,{waitUntil:'domcontentloaded'});
  const app=page.frameLocator('iframe[title="streamlitApp"]');
  await app.getByRole('heading',{name:/生詞題庫生成系統/}).waitFor({timeout:60000});
  for(const name of [/全自動 TTS/,/個人化弱點動態/]){
    const checkbox=app.getByRole('checkbox',{name});
    if(await checkbox.isChecked()) await checkbox.press('Space');
    assert.equal(await checkbox.isChecked(),false);
  }
  await app.getByRole('tab',{name:/統一打包匯出/}).click();
  await app.getByRole('button',{name:/點此生成\/更新題庫/}).click();
  const download=page.waitForEvent('download');
  await app.getByRole('button',{name:/下載.*GIFT 檔/}).click();
  const file=await download;
  const gift=await readFile(await file.path(),'utf8');
  assert.match(gift,/\$CATEGORY:/);
  assert.match(gift,/::.*::/);
  await app.getByRole('link',{name:'VocabResearch 教師端'}).click();
  await app.getByRole('heading',{name:'VocabResearch 教師端'}).waitFor();
  await app.getByText(/教師端尚未設定/).waitFor();
  assert.equal(await app.getByText(/研究資料與分析/).count(),0);
});
