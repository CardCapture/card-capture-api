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
    console.log("Starting hourly card scan notification process...");

    // Get the API URL from environment or default to Cloud Run
    const apiUrl = Deno.env.get("API_URL") ||
      "https://card-capture-api-878585200500.us-central1.run.app";

    const notificationEndpoint = `${apiUrl}/notifications/process-hourly`;

    console.log(`Calling notification endpoint: ${notificationEndpoint}`);

    // Call the API endpoint to process notifications
    const response = await fetch(notificationEndpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        // Include authorization if needed
        ...(Deno.env.get("API_SERVICE_KEY") ? {
          "Authorization": `Bearer ${Deno.env.get("API_SERVICE_KEY")}`
        } : {})
      },
      body: JSON.stringify({
        timestamp: new Date().toISOString(),
      }),
    });

    if (!response.ok) {
      const errorText = await response.text();
      throw new Error(
        `API responded with status: ${response.status}. ${errorText}`
      );
    }

    const result = await response.json();
    console.log("Notification processing completed:", result);

    return new Response(
      JSON.stringify({
        success: true,
        message: "Hourly notifications processed successfully",
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
    console.error("Error processing notifications:", error);

    return new Response(
      JSON.stringify({
        success: false,
        error: error.message,
        timestamp: new Date().toISOString(),
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
