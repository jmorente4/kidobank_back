from fastapi import APIRouter

router = APIRouter()

@router.get("/", summary="Listar cuentas del usuario")
def get_user_accounts():
    return {"msg": "Endpoint de cuentas bancarias"}