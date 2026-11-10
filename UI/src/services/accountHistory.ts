export interface KnownAccount { user_id: string; username: string }
type Store = Pick<Storage, 'getItem' | 'setItem'>
const KEY = 'promethea_known_accounts_v1'
const LIMIT = 12

function read(store: Store): KnownAccount[] {
  try {
    const value: unknown = JSON.parse(store.getItem(KEY) || '[]')
    if (!Array.isArray(value)) return []
    return value.filter((row): row is KnownAccount => Boolean(row && typeof row === 'object' && typeof row.user_id === 'string' && row.user_id && row.user_id.length <= 256 && typeof row.username === 'string' && row.username && row.username.length <= 256))
      .slice(0, LIMIT).map(({ user_id, username }) => ({ user_id, username }))
  } catch { return [] }
}

function write(store: Store, accounts: KnownAccount[]) {
  try { store.setItem(KEY, JSON.stringify(accounts.slice(0, LIMIT))) } catch { /* Storage may be disabled. */ }
}

export function knownAccounts(local: Store, session: Store): KnownAccount[] {
  return [...new Map([...read(session), ...read(local)].map((account) => [account.user_id, account])).values()].slice(0, LIMIT)
}

export function rememberAccount(local: Store, session: Store, profile: KnownAccount, persistent: boolean): KnownAccount[] {
  // Copy the display identity only; never retain a profile/token/password object.
  const account = { user_id: profile.user_id, username: profile.username }
  const others = (store: Store) => read(store).filter((row) => row.user_id !== account.user_id)
  write(local, persistent ? [account, ...others(local)] : others(local))
  write(session, persistent ? others(session) : [account, ...others(session)])
  return knownAccounts(local, session)
}

export function forgetAccount(local: Store, session: Store, userId: string): KnownAccount[] {
  for (const store of [local, session]) write(store, read(store).filter((row) => row.user_id !== userId))
  return knownAccounts(local, session)
}
