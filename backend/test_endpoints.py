import requests
import json

def test_django_endpoints():
    email = "nour@gmail.com"
    new_password = "password123!"

    print("Calling ForcerNouveauMotPasseView...")
    reset_res = requests.post(
        "http://localhost:8000/api/auth/reset-password/",
        json={"username": email, "new_password": new_password}
    )
    print("Reset Status:", reset_res.status_code)
    print("Reset Body:", reset_res.json())

    print("Calling LoginView...")
    login_res = requests.post(
        "http://localhost:8000/api/auth/login/",
        json={"email": email, "password": new_password}
    )
    print("Login Status:", login_res.status_code)
    print("Login Body:", login_res.json())

if __name__ == "__main__":
    test_django_endpoints()
