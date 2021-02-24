import { getBatchedDocumentStoreTaskEnvConfig } from 'src/config';
import { Batch, RestoreBatch } from 'src/tasks';
import {
  BatchDocuments,
} from 'src/repos';
import {
  clearBucket,
  generateDocumentsMap,
} from 'tests/utils';


describe('RestoreBatch task integration tests', ()=>{
  jest.setTimeout(1000 * 100);
  const config = getBatchedDocumentStoreTaskEnvConfig();

  beforeEach(async (done)=>{
    await clearBucket(config.BATCH_BUCKET_NAME);
    done();
  }, 1000 * 60);

  const batchDocuments = new BatchDocuments(config);

  test('restore batch, batch.restored=true, batch.composed=true', async ()=>{
    const documentsCount = 10;
    const expectedBatchDocumentsCount = 5;
    const documents = generateDocumentsMap(documentsCount);
    let batchSizeBytes = 0;
    let documentIndex = 0;
    for(let [key, document] of documents){
      await batchDocuments.put({Key: key, Body: JSON.stringify(document)});
      if(documentIndex < expectedBatchDocumentsCount){
        const s3Object = await batchDocuments.get({Key: key});
        batchSizeBytes += s3Object.ContentLength!;
      }
      documentIndex++;
    }


    const batch = new Batch();
    const restoreBatch = new RestoreBatch({
      batch,
      batchDocuments,
      batchTimeSeconds: 60,
      batchSizeBytes,
      attempts: 1,
      attemptsIntervalSeconds: 1
    });

    await restoreBatch.start();

    expect(batch.restored).toBe(true);
    expect(batch.composed).toBe(true);
    expect(batch.unwrappedDocuments.size).toBe(expectedBatchDocumentsCount);
    for(let [key, document] of batch.unwrappedDocuments){
      const s3Object = await batchDocuments.get({Key: key});
      expect(JSON.parse(s3Object.Body!.toString())).toEqual(document.body);
    }
  })

  test('restore batch, batch.restored=true, batch.composed=false', async ()=>{
    const documents = generateDocumentsMap(10);
    for(let [key, document] of documents){
      await batchDocuments.put({Key: key, Body: JSON.stringify(document)});
    }


    const batch = new Batch();
    const restoreBatch = new RestoreBatch({
      batch,
      batchDocuments,
      batchTimeSeconds: 60,
      batchSizeBytes: 1024 * 1024 * 1024,
      attempts: 1,
      attemptsIntervalSeconds: 1
    });

    await restoreBatch.start();

    expect(batch.restored).toBe(true);
    expect(batch.composed).toBe(false);
    expect(batch.unwrappedDocuments.size).toBe(documents.size);
    for(let [key, document] of batch.unwrappedDocuments){
      const s3Object = await batchDocuments.get({Key: key});
      expect(JSON.parse(s3Object.Body!.toString())).toEqual(document.body);
    }
  })

  test('restore batch, batch.restored=false, batch.composed=false', async ()=>{
    const batch = new Batch();
    const restoreBatch = new RestoreBatch({
      batch,
      batchDocuments,
      batchTimeSeconds: 60,
      batchSizeBytes: 1024 * 1024 * 1024,
      attempts: 1,
      attemptsIntervalSeconds: 1
    });

    await restoreBatch.start();

    expect(batch.restored).toBe(false);
    expect(batch.composed).toBe(false);
    expect(batch.unwrappedDocuments.size).toBe(0);
  })
});
