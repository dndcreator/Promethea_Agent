import assert from 'node:assert/strict'
import test from 'node:test'
import { knownAccounts, rememberAccount, forgetAccount } from '../src/services/accountHistory.ts'

const storage = () => {
  const values = new Map()
  return { values, getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) }
}

test('account selection retains display identity only, never reusable credentials', () => {
  const local = storage(), session = storage()
  rememberAccount(local, session, { user_id: 'alice', username: 'Alice', token: 'SECRET', password: 'PASSWORD' }, true)
  assert.deepEqual(knownAccounts(local, session), [{ user_id: 'alice', username: 'Alice' }])
  assert(!JSON.stringify([...local.values]).includes('SECRET'))
  assert(!JSON.stringify([...local.values]).includes('PASSWORD'))
  rememberAccount(local, session, { user_id: 'alice', username: 'Alice renamed' }, true)
  assert.equal(knownAccounts(local, session).length, 1)
  assert.equal(knownAccounts(local, session)[0].username, 'Alice renamed')
})

test('non-remembered identities remain session-only, and forgetting never changes auth tokens', () => {
  const local = storage(), session = storage()
  local.setItem('auth_token', 'CURRENT')
  rememberAccount(local, session, { user_id: 'alice', username: 'Alice' }, true)
  rememberAccount(local, session, { user_id: 'alice', username: 'Alice' }, false)
  assert.deepEqual(knownAccounts(local, storage()), [])
  assert.equal(knownAccounts(local, session).length, 1)
  forgetAccount(local, session, 'alice')
  assert.deepEqual(knownAccounts(local, session), [])
  assert.equal(local.getItem('auth_token'), 'CURRENT')
})

test('malformed or denied storage stays bounded and cannot inject credential fields', () => {
  const local = storage(), session = storage()
  const key = 'promethea_known_accounts_v1'
  local.setItem(key, '{invalid')
  assert.deepEqual(knownAccounts(local, session), [])
  local.setItem(key, JSON.stringify([null, { user_id: 3, username: 'bad' }, ...Array.from({ length: 40 }, (_, i) => ({ user_id: String(i), username: `User ${i}`, token: 'DROP' }))]))
  assert.equal(knownAccounts(local, session).length, 12)
  assert(knownAccounts(local, session).every(account => !('token' in account)))
  const denied = { getItem() { throw new Error('denied') }, setItem() { throw new Error('denied') } }
  assert.doesNotThrow(() => rememberAccount(denied, denied, { user_id: 'a', username: 'A' }, true))
})
