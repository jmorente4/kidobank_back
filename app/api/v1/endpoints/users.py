from fastapi import APIRouter

router = APIRouter()

@router.get("/me", summary="Obtener perfil del usuario actual")
def get_current_user_profile():
    return {"msg": "Endpoint de perfil de usuario"}