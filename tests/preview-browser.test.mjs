import test from 'node:test';
import assert from 'node:assert/strict';
import { createServer } from 'node:http';
import { execFileSync } from 'node:child_process';

test('Chrome renders all three stages of the Streamlit-generated preview',async t=>{
  const fixture = `from core import validate_and_build
from preview import preview_html
import sys
_, course, _ = validate_and_build("fixture", {"冊":"一","課":"一"}, [
    {"word":"甲","pinyin":"jiǎ","meanings":{"en":"new card","vi":"vietnamese-甲","id":"indonesian-甲"},"sentence":"這句＿＿要存檔。","accepted":["新選項"]}
], {"id":"IT_PREVIEW","version":"v1","title":"合成預覽"}, preview=True)
sys.stdout.buffer.write(preview_html(course, "student").encode("utf-8"))
`;
  const html=execFileSync(process.env.VOCAB_PYTHON||'python',['-c',fixture],{encoding:'utf8'});
  const { chromium }=await import(process.env.VOCAB_PLAYWRIGHT_ENTRY||'playwright-core');
  const server=createServer((req,res)=>{
    res.setHeader('content-type','text/html; charset=utf-8');
    res.end(req.url==='/preview'?html:'<iframe title="教師預覽" sandbox="allow-scripts allow-same-origin" src="/preview"></iframe>');
  });
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const browser=await chromium.launch({executablePath:process.env.VOCAB_E2E_CHROME,headless:true});
  t.after(async()=>{await browser.close();await new Promise(resolve=>server.close(resolve));});
  const page=await browser.newPage();
  let networkWrites=0;
  page.on('request',r=>{if(r.method()==='POST')networkWrites++;});
  await page.goto('http://127.0.0.1:'+server.address().port);
  const preview=page.frameLocator('iframe');
  const show=async(stage,language)=>{
    await preview.locator('#previewStage').selectOption(stage);
    await preview.locator('#language').selectOption(language);
    await preview.locator('#start').click();
  };
  await t.test('flashcard shows edited meaning and pinyin',async()=>{
    await show('0','en');
    await preview.locator('#flip').click();
    const text=await preview.locator('#flip').innerText();
    assert.match(text,/甲/);
    assert.match(text,/jiǎ/);
    assert.match(text,/new card/);
  });
  await t.test('matching uses the selected configured language and included word',async()=>{
    await show('1','vi');
    assert.equal(await preview.locator('[data-left]').innerText(),'甲');
    assert.equal(await preview.locator('[data-right]').innerText(),'vietnamese-甲');
    await preview.locator('[data-left]').click();
    await preview.locator('[data-right]').click();
    assert.equal(await preview.locator('#nextGroup').isEnabled(),true);
  });
  await t.test('cloze shows the edited prompt and validates the new alias locally',async()=>{
    await show('2','id');
    assert.match(await preview.locator('#screen').innerText(),/這句＿＿要存檔。/);
    await preview.locator('[data-fill]').fill('新選項');
    await preview.locator('#submitCloze').click();
    assert.match(await preview.locator('#screen').innerText(),/預覽練習完成/);
    assert.equal(networkWrites,0);
  });
});
