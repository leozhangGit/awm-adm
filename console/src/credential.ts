export async function sealCredential(
  key: { key_id: string; spki: string } | null,
  credential: string,
  provider: string,
  idempotencyKey: string,
) {
  if (!key) throw Error("Wait for the credential gateway to become ready.");
  const spki = Uint8Array.from(atob(key.spki), (c) => c.charCodeAt(0));
  const publicKey = await crypto.subtle.importKey(
    "spki",
    spki,
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["encrypt"],
  );
  const plaintext = new TextEncoder().encode(
    JSON.stringify({ credential, provider, idempotency_key: idempotencyKey }),
  );
  try {
    const result = await crypto.subtle.encrypt(
      {
        name: "RSA-OAEP",
        label: new TextEncoder().encode("awm-adm-provider-credential/1"),
      },
      publicKey,
      plaintext,
    );
    return {
      sealed_credential: btoa(String.fromCharCode(...new Uint8Array(result))),
      sealing_key_id: key.key_id,
    };
  } finally {
    plaintext.fill(0);
  }
}
