import { serve } from "https://deno.land/std@0.168.0/http/server.ts";

const corsHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Headers":
    "authorization, x-client-info, apikey, content-type",
};

serve(async (req) => {
  // Handle CORS preflight requests
  if (req.method === "OPTIONS") {
    return new Response("ok", { headers: corsHeaders });
  }

  try {
    const { record } = await req.json();

    if (!record || !record.id) {
      throw new Error("No job ID found in the request");
    }

    const jobId = record.id;
    console.log(`Processing job trigger for jobId: ${jobId}`);

    // Make request to Cloud Run service with /process endpoint (now using unified worker with V3)
    const cloudRunUrl = Deno.env.get("WORKER_URL");
    if (!cloudRunUrl) {
      throw new Error("WORKER_URL environment variable is not set. Configure it in Supabase Edge Function secrets.");
    }

    const response = await fetch(cloudRunUrl, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        job_id: jobId,
        timestamp: new Date().toISOString(),
      }),
    });

    if (!response.ok) {
      throw new Error(
        `Cloud Run service responded with status: ${response.status}`
      );
    }

    const result = await response.json();
    console.log(
      `Successfully triggered Cloud Run service for jobId: ${jobId}`,
      result
    );

    return new Response(
      JSON.stringify({
        message: "Job trigger processed successfully",
        jobId: jobId,
        cloudRunResponse: result,
      }),
      {
        headers: {
          ...corsHeaders,
          "Content-Type": "application/json",
        },
      }
    );
  } catch (error) {
    console.error("Error processing job trigger:", error);

    return new Response(
      JSON.stringify({
        error: error.message,
      }),
      {
        status: 400,
        headers: {
          ...corsHeaders,
          "Content-Type": "application/json",
        },
      }
    );
  }
});
