from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import can_access_user, get_family_user_ids, get_current_child, get_current_parent, get_current_user, get_db
from app.models.account import Account, AccountType
from app.models.task import Task, TaskStatus
from app.models.transaction import Transaction, TransactionStatus, TransactionType
from app.models.user import ADMIN_ROLES, MEMBER_ROLES, User
from app.schemas.task import TaskApprove, TaskCreate, TaskResponse

router = APIRouter()


@router.delete(
    "/{task_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Eliminar una tarea en estado asignada",
)
def delete_task(
    task_id: int,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    child = db.get(User, task.usuario_id)
    if child is None or not can_access_user(current_parent, child):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    if task.estado != TaskStatus.ASIGNADA:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Solo se pueden eliminar tareas asignadas, no pendientes de aprobación ni aprobadas",
        )
    db.delete(task)
    db.commit()


@router.get("", response_model=List[TaskResponse], summary="Listar las tareas visibles para el usuario")
def list_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    stmt = select(Task).order_by(Task.created_at.desc(), Task.id.desc())
    if current_user.rol in ADMIN_ROLES:
        stmt = stmt.where(Task.usuario_id.in_(get_family_user_ids(current_user, db)))
    else:
        stmt = stmt.where(Task.usuario_id == current_user.id)
    return db.scalars(stmt).all()


@router.post("", response_model=TaskResponse, status_code=status.HTTP_201_CREATED, summary="Asignar una tarea a NINO/FAMILIAR")
def create_task(
    payload: TaskCreate,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    child = db.get(User, payload.usuario_id)
    if child is None or child.rol not in MEMBER_ROLES or not can_access_user(current_parent, child):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Miembro no encontrado")

    task = Task(
        usuario_id=child.id,
        creado_por_id=current_parent.id,
        titulo=payload.titulo,
        descripcion=payload.descripcion,
        recompensa_kidos=payload.recompensa_kidos,
        estado=TaskStatus.ASIGNADA,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


@router.post(
    "/{task_id}/complete",
    response_model=TaskResponse,
    summary="Marcar una tarea como completada para revisión",
)
def complete_task(
    task_id: int,
    current_child: User = Depends(get_current_child),
    db: Session = Depends(get_db),
):
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    if task.usuario_id != current_child.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="La tarea no está asignada a este miembro")
    if task.estado != TaskStatus.ASIGNADA:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La tarea ya está completada o pendiente de aprobación")

    task.estado = TaskStatus.PENDIENTE_APROBACION
    task.completada_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(task)
    return task


@router.post(
    "/{task_id}/approve",
    response_model=TaskResponse,
    summary="Aprobar una tarea y abonar su recompensa",
)
def approve_task(
    task_id: int,
    payload: TaskApprove,
    current_parent: User = Depends(get_current_parent),
    db: Session = Depends(get_db),
):
    task = db.scalar(select(Task).where(Task.id == task_id).with_for_update())
    if task is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")

    child = db.get(User, task.usuario_id)
    if child is None or not can_access_user(current_parent, child):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Tarea no encontrada")
    if task.estado != TaskStatus.PENDIENTE_APROBACION:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La tarea no está pendiente de aprobación")

    account = db.scalar(select(Account).where(Account.id == payload.cuenta_id).with_for_update())
    if account is None or account.usuario_id != child.id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cuenta del hijo no encontrada")
    if account.tipo != AccountType.CORRIENTE:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="La recompensa debe abonarse en una cuenta corriente")

    account.saldo += task.recompensa_kidos
    task.estado = TaskStatus.COMPLETADA
    task.cuenta_abono_id = account.id
    task.aprobada_por_id = current_parent.id
    task.aprobada_at = datetime.now(timezone.utc)
    db.add(
        Transaction(
            cuenta_origen_id=None,
            cuenta_destino_id=account.id,
            monto=task.recompensa_kidos,
            concepto=f"Recompensa por tarea: {task.titulo}",
            tipo=TransactionType.RECOMPENSA,
            estado=TransactionStatus.COMPLETADA,
        )
    )
    db.commit()
    db.refresh(task)
    return task
