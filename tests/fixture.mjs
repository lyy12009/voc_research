import { readFile } from 'node:fs/promises';
const { PGlite } = await import(process.env.VOCAB_PGLITE_ENTRY || '@electric-sql/pglite');
const { pgcrypto } = await import(process.env.VOCAB_PGLITE_CRYPTO || '@electric-sql/pglite/contrib/pgcrypto');

export async function fixture(dataDir) {
  const db = new PGlite({dataDir,extensions:{pgcrypto}});
  await db.exec('create role anon; create role authenticated');
  for (const migration of ['202611250001_vocab', '202611250002_private_cloze', '202611250003_cloud_teacher', '202611250004_research', '202611250005_delayed']) {
    await db.exec(await readFile(new URL('../supabase/migrations/'+migration+'.sql', import.meta.url), 'utf8'));
  }
  await db.exec("insert into vocab_teacher.identities values ('https://issuer.test','teacher-A',true),('https://issuer.test','teacher-B',true)");
  return db;
}

export const words = [
  {id:'W1',word:'甲',pinyin:'jiǎ',meanings:{en:'alpha'},sentence:'這是＿＿的例子。'},
  {id:'W2',word:'乙',pinyin:'yǐ',meanings:{en:'beta'},sentence:'這是另一個＿＿。'},
];

export async function teacher(db, operation, packet={}, subject='teacher-A') {
  const result = await db.query('select vocab_teacher.request($1,$2,$3,$4) as result', ['https://issuer.test',subject,operation,packet]);
  return result.rows[0].result;
}

export async function seed(db, courseId, code, pin) {
  await teacher(db,'student',{code,pin});
  for (const version of ['v1','v2']) {
    await teacher(db,'course',{document:{id:courseId, version, title:'合成教材',
      words:words.map((word,i)=>({...word,accepted:i===0?['先修詞']:[]}))},manifest:{fixture:true}});
  }
}
