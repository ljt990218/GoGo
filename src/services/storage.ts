import type { AnalysisRecord, GameRecord, MoveReviewRecord } from '../domain/types'

let database: Promise<IDBDatabase> | null = null

function openDatabase(): Promise<IDBDatabase> {
  if (database) return database
  database = new Promise((resolve, reject) => {
    const request = indexedDB.open('gogo-review', 3)
    request.onupgradeneeded = event => {
      const db = request.result
      if (!db.objectStoreNames.contains('games')) db.createObjectStore('games', { keyPath: 'gameId' })
      if (!db.objectStoreNames.contains('analyses')) {
        const analyses = db.createObjectStore('analyses', { keyPath: ['gameId', 'moveIndex'] })
        analyses.createIndex('gameId', 'gameId')
      }
      if (!db.objectStoreNames.contains('moveReviews')) {
        const reviews = db.createObjectStore('moveReviews', { keyPath: ['gameId', 'moveIndex'] })
        reviews.createIndex('gameId', 'gameId')
      }
      if (event.oldVersion < 2) {
        request.transaction!.objectStore('analyses').openCursor().onsuccess = event => {
          const cursor = (event.target as IDBRequest<IDBCursorWithValue | null>).result
          if (!cursor) return
          const record = cursor.value as AnalysisRecord
          if (record.candidateIndex === undefined) cursor.update({ ...record, candidateIndex: 0 })
          cursor.continue()
        }
      }
    }
    request.onsuccess = () => {
      const db = request.result
      db.onversionchange = () => {
        db.close()
        database = null
      }
      resolve(db)
    }
    request.onerror = () => reject(new Error('无法打开本地存储，请检查浏览器网站权限'))
    request.onblocked = () => reject(new Error('本地存储被其他页面占用，请关闭其他 GoGo 页面后重试'))
  }).catch(error => {
    database = null
    throw error
  })
  return database
}

async function transaction<T>(stores: string[], mode: IDBTransactionMode, work: (tx: IDBTransaction, result: (value: T) => void) => void): Promise<T> {
  const db = await openDatabase()
  return new Promise((resolve, reject) => {
    const tx = db.transaction(stores, mode)
    let result: T
    tx.oncomplete = () => resolve(result)
    tx.onabort = () => reject(new Error('本地存储操作失败，可能是存储空间不足或网站权限受限'))
    tx.onerror = () => reject(new Error('本地存储操作失败，请检查可用空间与浏览器权限'))
    try {
      work(tx, value => { result = value })
    } catch (error) {
      tx.abort()
      reject(error)
    }
  })
}

export function listGames(): Promise<GameRecord[]> {
  return transaction(['games'], 'readonly', (tx, result) => {
    tx.objectStore('games').getAll().onsuccess = event => result((event.target as IDBRequest<GameRecord[]>).result)
  })
}

export function getGame(gameId: string): Promise<GameRecord | undefined> {
  return transaction(['games'], 'readonly', (tx, result) => {
    tx.objectStore('games').get(gameId).onsuccess = event => result((event.target as IDBRequest<GameRecord | undefined>).result)
  })
}

export function listAnalyses(gameId: string): Promise<AnalysisRecord[]> {
  return transaction(['analyses'], 'readonly', (tx, result) => {
    tx.objectStore('analyses').index('gameId').getAll(gameId).onsuccess = event => result((event.target as IDBRequest<AnalysisRecord[]>).result)
  })
}

export function listMoveReviews(gameId: string): Promise<MoveReviewRecord[]> {
  return transaction(['moveReviews'], 'readonly', (tx, result) => {
    tx.objectStore('moveReviews').index('gameId').getAll(gameId).onsuccess = event => result((event.target as IDBRequest<MoveReviewRecord[]>).result)
  })
}

export function saveMoveReview(record: MoveReviewRecord): Promise<void> {
  return transaction(['games', 'moveReviews'], 'readwrite', tx => {
    tx.objectStore('games').getKey(record.gameId).onsuccess = event => {
      if ((event.target as IDBRequest).result === undefined) return tx.abort()
      tx.objectStore('moveReviews').put(record)
    }
  })
}

export function analysisCounts(): Promise<Record<string, number>> {
  return transaction(['analyses', 'moveReviews'], 'readonly', (tx, result) => {
    const counts: Record<string, number> = {}
    for (const name of ['analyses', 'moveReviews']) {
      tx.objectStore(name).index('gameId').openKeyCursor().onsuccess = event => {
        const cursor = (event.target as IDBRequest<IDBCursor | null>).result
        if (!cursor) return
        const gameId = String(cursor.key)
        counts[gameId] = (counts[gameId] ?? 0) + 1
        cursor.continue()
      }
    }
    result(counts)
  })
}

export function saveGame(game: GameRecord): Promise<void> {
  return transaction(['games'], 'readwrite', tx => { tx.objectStore('games').put(game) })
}

export function saveAnalysis(record: AnalysisRecord): Promise<void> {
  return transaction(['games', 'analyses'], 'readwrite', tx => {
    tx.objectStore('games').getKey(record.gameId).onsuccess = event => {
      if ((event.target as IDBRequest).result === undefined) return tx.abort()
      tx.objectStore('analyses').put(record)
    }
  })
}

export function saveExplanation(record: AnalysisRecord): Promise<void> {
  return transaction(['analyses'], 'readwrite', tx => {
    const store = tx.objectStore('analyses')
    store.get([record.gameId, record.moveIndex]).onsuccess = event => {
      const saved = (event.target as IDBRequest<AnalysisRecord | undefined>).result
      if (!saved || saved.analysis.analyzedAt !== record.analysis.analyzedAt) return tx.abort()
      store.put({
        ...saved,
        candidateIndex: record.candidateIndex ?? 0,
        explanation: record.explanation,
        aiModel: record.aiModel,
        explainedAt: record.explainedAt
      })
    }
  })
}

export function deleteGame(gameId: string): Promise<void> {
  return transaction(['games', 'analyses', 'moveReviews'], 'readwrite', tx => {
    tx.objectStore('games').delete(gameId)
    for (const name of ['analyses', 'moveReviews']) {
      tx.objectStore(name).index('gameId').openCursor(IDBKeyRange.only(gameId)).onsuccess = event => {
        const cursor = (event.target as IDBRequest<IDBCursorWithValue | null>).result
        if (cursor) {
          cursor.delete()
          cursor.continue()
        }
      }
    }
  })
}
