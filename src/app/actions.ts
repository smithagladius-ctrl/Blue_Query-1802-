'use server';

interface AiChatResult {
    response?: string;
    reportDataUri?: string;
    error?: string;
}

const BACKEND_URL = process.env.BACKEND_URL || 'http://127.0.0.1:8000';
const BACKEND_QUERY_ENDPOINT = `${BACKEND_URL.replace(/\/$/, '')}/query`;

async function queryBackend(query: string): Promise<string> {
    const response = await fetch(BACKEND_QUERY_ENDPOINT, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query }),
        cache: 'no-store',
    });

    if (!response.ok) {
        let details = '';
        try {
            details = await response.text();
        } catch {
            details = '';
        }
        throw new Error(`Backend request failed (${response.status}). ${details}`.trim());
    }

    const payload = await response.json();
    const result = payload?.result;
    if (typeof result === 'string' && result.trim()) {
        return result;
    }
    if (result && typeof result === 'object') {
        return JSON.stringify(result, null, 2);
    }
    return 'No response received from backend.';
}

function textToDataUri(text: string): string {
    const utf8Bytes = Buffer.from(text, 'utf-8');
    return `data:text/plain;base64,${utf8Bytes.toString('base64')}`;
}

export async function handleAiChat(query: string, forReport: boolean = false): Promise<AiChatResult> {
    try {
        const backendResult = await queryBackend(query);

        if (forReport) {
            return { reportDataUri: textToDataUri(backendResult) };
        }

        return { response: backendResult };
    } catch (e: any) {
        console.error('AI handler error:', e);
        return {
            error:
                e?.message ||
                'Could not reach backend. Start backend server and ensure BACKEND_URL is set correctly.',
        };
    }
}


export async function handleDashboardAiChat(query: string, mode: 'descriptive' | 'predictive', context?: any): Promise<AiChatResult> {
    try {
        let fullQuery = `Dashboard mode: ${mode}. User query: "${query}"`;
        if (mode === 'predictive' && context) {
            fullQuery += `\n\nPredictive context:\n${JSON.stringify(context, null, 2)}`;
        }
        const backendResult = await queryBackend(fullQuery);
        return { response: backendResult };

    } catch (e: any) {
        console.error('Dashboard AI handler error:', e);
        return {
            error:
                e?.message ||
                'Could not reach backend. Start backend server and ensure BACKEND_URL is set correctly.',
        };
    }
}
