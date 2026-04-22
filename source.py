from models import Model,ModelType

class Source:
    def __init__(self, name=None):
        self.name = name
        # self.model = Model(ModelType.POWER)
        self.model = Model(ModelType.LINEAR)
