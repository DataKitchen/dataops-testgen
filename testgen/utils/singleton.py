import typing


class SingletonType(type):
    _instances: typing.ClassVar[dict[type, object]] = {}

    def __call__(cls, *args, **kwargs) -> typing.Any:
        if cls not in cls._instances:
            cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class Singleton(metaclass=SingletonType):
    pass
