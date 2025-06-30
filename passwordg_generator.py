from werkzeug.security import generate_password_hash, check_password_hash

# 1. Generate a password hash
password_to_hash = "Kulang@1988"
hashed_password = generate_password_hash(password_to_hash)

print(f"Original Password: {password_to_hash}")
print(f"Hashed Password: {hashed_password}")

# 2. Verify a password against the hash
# Correct password
input_password_correct = "Kulang@1988"
if check_password_hash(hashed_password, input_password_correct):
    print(f"'{input_password_correct}' is a CORRECT password.")
else:
    print(f"'{input_password_correct}' is an INCORRECT password.")

# Incorrect password
input_password_incorrect = "WrongPassword456"
if check_password_hash(hashed_password, input_password_incorrect):
    print(f"'{input_password_incorrect}' is a CORRECT password.")
else:
    print(f"'{input_password_incorrect}' is an INCORRECT password.")

# You can also specify a different method and salt length (though often not necessary)
# For example, using SHA512 with a longer salt:
hashed_password_sha512 = generate_password_hash(password_to_hash, method='pbkdf2:sha512', salt_length=16)
print(f"\nHashed Password (SHA512, longer salt): {hashed_password_sha512}")