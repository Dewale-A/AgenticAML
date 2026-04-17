// API proxy route - forwards all requests to the FastAPI backend
// This avoids CORS issues and keeps the backend URL server-side
import { NextRequest, NextResponse } from 'next/server'

const API_URL = process.env.API_URL || 'http://localhost:8003'

export async function GET(request: NextRequest) {
  // Extract the path after /api/proxy
  const url = request.nextUrl
  const targetPath = url.searchParams.get('path') || '/'
  const queryString = url.searchParams.get('query') || ''

  const targetUrl = `${API_URL}${targetPath}${queryString ? '?' + queryString : ''}`

  try {
    const response = await fetch(targetUrl, {
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      // No caching - always fresh data
      cache: 'no-store',
    })

    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    console.error('Proxy error:', error)
    return NextResponse.json(
      { error: 'Backend unavailable', detail: String(error) },
      { status: 503 }
    )
  }
}

export async function POST(request: NextRequest) {
  const url = request.nextUrl
  const targetPath = url.searchParams.get('path') || '/'
  const body = await request.json()

  const targetUrl = `${API_URL}${targetPath}`

  try {
    const response = await fetch(targetUrl, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(body),
    })

    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    console.error('Proxy error:', error)
    return NextResponse.json(
      { error: 'Backend unavailable', detail: String(error) },
      { status: 503 }
    )
  }
}

export async function PUT(request: NextRequest) {
  const url = request.nextUrl
  const targetPath = url.searchParams.get('path') || '/'
  const body = await request.json()

  const targetUrl = `${API_URL}${targetPath}`

  try {
    const response = await fetch(targetUrl, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json',
      },
      body: JSON.stringify(body),
    })

    const data = await response.json()
    return NextResponse.json(data, { status: response.status })
  } catch (error) {
    return NextResponse.json({ error: 'Backend unavailable' }, { status: 503 })
  }
}
