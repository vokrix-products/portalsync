import React, { useEffect, useState } from 'react'
import { createClient } from '@supabase/supabase-js'

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || ''
const supabaseKey = import.meta.env.VITE_SUPABASE_ANON_KEY || ''
const supabase = supabaseUrl && supabaseKey ? createClient(supabaseUrl, supabaseKey) : null

const PRODUCT_NAME = import.meta.env.VITE_PRODUCT_NAME || 'PortalSync'
const PRODUCT_DESCRIPTION = import.meta.env.VITE_PRODUCT_DESCRIPTION || ''
const PAYWALL_TITLE = import.meta.env.VITE_PAYWALL_TITLE || 'You have used your 3 free Policys'
const PAYWALL_DESCRIPTION = import.meta.env.VITE_PAYWALL_DESCRIPTION || 'Upgrade to get unlimited Policys.'

export default function App() {
  const [policies, setPolicies] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  useEffect(() => {
    async function load() {
      if (!supabase) {
        setError('Supabase is not configured.')
        setLoading(false)
        return
      }
      try {
        const { data, error } = await supabase
          .from('policies')
          .select('*')
          .limit(5)
        if (error) throw error
        setPolicies(data || [])
      } catch (e) {
        setError(e.message || 'Failed to load policies.')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  const locked = policies.length >= 3

  return (
    <div style={styles.page}>
      <header style={styles.header}>
        <h1>{PRODUCT_NAME}</h1>
        <p>{PRODUCT_DESCRIPTION}</p>
      </header>
      <main style={styles.main}>
        <h2>Policies</h2>
        {loading && <p>Loading policies...</p>}
        {error && <p style={styles.error}>{error}</p>}
        {!loading && !error && policies.length === 0 && (
          <p>No policies found yet. Upload your first policy to get started.</p>
        )}
        <ul style={styles.list}>
          {policies.map((p) => (
            <li key={p.id || p.policy_number || JSON.stringify(p)} style={styles.card}>
              <strong>{p.policy_number || p.carrier || 'Policy'}</strong>
              <span>{p.insured_name || p.status || ''}</span>
            </li>
          ))}
        </ul>
        {!loading && locked && (
          <div style={styles.paywall}>
            <h3>{PAYWALL_TITLE}</h3>
            <p>{PAYWALL_DESCRIPTION}</p>
            <button style={styles.button} onClick={() => alert('Upgrade coming soon. Contact your agency.')}>Upgrade</button>
          </div>
        )}
      </main>
    </div>
  )
}

const styles = {
  page: { minHeight: '100vh', background: '#f6f8fb', color: '#0f172a', fontFamily: 'system-ui, sans-serif' },
  header: { background: '#1e293b', color: '#f8fafc', padding: '40px 24px', textAlign: 'center' },
  headerH1: { margin: 0, fontSize: '2.2rem' },
  headerP: { color: '#cbd5e1', marginTop: 8 },
  main: { maxWidth: 720, margin: '0 auto', padding: 32 },
  list: { listStyle: 'none', padding: 0, display: 'grid', gap: 12 },
  card: { background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, padding: 16, display: 'flex', flexDirection: 'column', gap: 4 },
  error: { color: '#b91c1c', background: '#fee2e2', padding: 12, borderRadius: 8 },
  paywall: { marginTop: 32, background: '#fff7ed', border: '1px solid #fdba74', borderRadius: 12, padding: 24, textAlign: 'center' },
  button: { background: '#f97316', color: '#fff', border: 'none', borderRadius: 8, padding: '10px 20px', fontSize: '1rem', cursor: 'pointer', marginTop: 8 },
}
