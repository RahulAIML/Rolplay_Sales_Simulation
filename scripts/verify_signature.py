from services import whatsapp_service
import inspect

print("Function Signature:")
print(inspect.signature(whatsapp_service.send_whatsapp_message))

if "use_template" in str(inspect.signature(whatsapp_service.send_whatsapp_message)):
    print("✅ Local version has 'use_template'")
else:
    print("❌ Local version MISSING 'use_template'")
