import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

// Retry configuration
const MAX_RETRIES = 3;
const INITIAL_RETRY_DELAY_MS = 2000; // 2 seconds
const REQUEST_TIMEOUT_MS = 30000; // 30 seconds per attempt

// Helper function to add timeout to fetch
async function fetchWithTimeout(url: string, options: RequestInit, timeoutMs: number) {
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });
    clearTimeout(timeoutId);
    return response;
  } catch (error) {
    clearTimeout(timeoutId);
    if (error.name === 'AbortError') {
      throw new Error(`Request timeout after ${timeoutMs}ms`);
    }
    throw error;
  }
}

// Helper function to call API with retry logic
async function callApiWithRetry(url: string, options: RequestInit, maxRetries: number) {
  let lastError: Error;

  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    const attemptStartTime = Date.now();
    console.log(`Attempt ${attempt}/${maxRetries} - Calling ${url}`);

    try {
      const response = await fetchWithTimeout(url, options, REQUEST_TIMEOUT_MS);
      const duration = Date.now() - attemptStartTime;
      console.log(`Attempt ${attempt} completed in ${duration}ms with status ${response.status}`);

      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(`API responded with status: ${response.status}. ${errorText}`);
      }

      return response;
    } catch (error) {
      const duration = Date.now() - attemptStartTime;
      lastError = error;
      console.error(`Attempt ${attempt} failed after ${duration}ms:`, error.message);

      // If this isn't the last attempt, wait before retrying
      if (attempt < maxRetries) {
        const delayMs = INITIAL_RETRY_DELAY_MS * attempt; // Exponential backoff
        console.log(`Waiting ${delayMs}ms before retry...`);
        await new Promise(resolve => setTimeout(resolve, delayMs));
      }
    }
  }

  throw new Error(`All ${maxRetries} attempts failed. Last error: ${lastError.message}`);
}

serve(async (req) => {
  // Handle CORS preflight requests
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  const startTime = Date.now();
  const requestTimestamp = new Date().toISOString();

  try {
    console.log(`[${requestTimestamp}] Starting hourly card scan notification process...`);

    // Get the API URL from environment or default to Cloud Run
    const apiUrl = Deno.env.get("API_URL") ||
      "https://card-capture-be-staging-878585200500.us-central1.run.app";

    const notificationEndpoint = `${apiUrl}/notifications/process-hourly`;

    console.log(`Target endpoint: ${notificationEndpoint}`);
    console.log(`Max retries: ${MAX_RETRIES}, Timeout per attempt: ${REQUEST_TIMEOUT_MS}ms`);

    // Webhook secret for authenticating with the API
    const webhookSecret = Deno.env.get("NOTIFICATION_WEBHOOK_SECRET");
    if (!webhookSecret) {
      throw new Error("NOTIFICATION_WEBHOOK_SECRET not configured");
    }

    // Call the API endpoint to process notifications with retry logic
    const response = await callApiWithRetry(
      notificationEndpoint,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-Webhook-Secret": webhookSecret,
          ...(Deno.env.get("API_SERVICE_KEY") ? {
            "Authorization": `Bearer ${Deno.env.get("API_SERVICE_KEY")}`
          } : {})
        },
        body: JSON.stringify({
          timestamp: requestTimestamp,
        }),
      },
      MAX_RETRIES
    );

    const result = await response.json();
    const totalDuration = Date.now() - startTime;

    console.log(`✓ Notification processing completed successfully in ${totalDuration}ms:`, result);

    return new Response(
      JSON.stringify({
        success: true,
        message: "Hourly notifications processed successfully",
        duration_ms: totalDuration,
        timestamp: requestTimestamp,
        ...result,
      }),
      {
        headers: {
          ...corsHeaders,
          "Content-Type": "application/json",
        },
      }
    );
  } catch (error) {
    const totalDuration = Date.now() - startTime;
    console.error(`✗ Error processing notifications after ${totalDuration}ms:`, error);

    return new Response(
      JSON.stringify({
        success: false,
        error: error.message,
        duration_ms: totalDuration,
        timestamp: requestTimestamp,
      }),
      {
        status: 500,
        headers: {
          ...corsHeaders,
          "Content-Type": "application/json",
        },
      }
    );
  }
});
