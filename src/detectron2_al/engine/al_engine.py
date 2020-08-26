import torch
import logging
import time
import weakref
import os
import pandas as pd
from torch.nn.parallel import DistributedDataParallel
from fvcore.nn.precise_bn import get_bn_modules

from detectron2.checkpoint import DetectionCheckpointer
from detectron2.utils.logger import setup_logger
from detectron2.utils import comm
from detectron2.evaluation import verify_results
from detectron2.engine import DefaultPredictor, DefaultTrainer, HookBase, hooks
from detectron2.evaluation import COCOEvaluator


from ..dataset.al_dataset import build_al_dataset
from ..dataset.object_fusion import ObjectFusion


def build_al_trainer(cfg):

    if cfg.AL.MODE == 'image':
        return ImageActiveLearningTrainer(cfg)
    elif cfg.AL.MODE == 'object':
        return ObjectActiveLearningTrainer(cfg)
    else:
        raise ValueError(f'Unknown active learning mode {cfg.AL.MODE}')


class ActiveLearningTrainer(DefaultTrainer):

    """
    Modified based on DefaultTrainer to support active 
    learning functions.
    """

    def __init__(self, cfg):

        logger = logging.getLogger("detectron2")
        if not logger.isEnabledFor(logging.INFO):  # setup_logger is not called for d2
            setup_logger()
        
        model = self.build_model(cfg)
        optimizer = self.build_optimizer(cfg, model)
        
        self.model = model
        self.optimizer = optimizer
        self.al_dataset = self.build_al_dataset(cfg)
        self.object_fusion = ObjectFusion(cfg)
        # It should be moved to ObjectActiveLearningTrainer later when

        # For training, wrap with DDP. But don't need this for inference.
        if comm.get_world_size() > 1:
            model = DistributedDataParallel(
                model, device_ids=[comm.get_local_rank()], broadcast_buffers=False
            )
        
        self.scheduler = self.build_lr_scheduler(cfg, optimizer)
        # Assume no other objects need to be checkpointed.
        # We can later make it checkpoint the stateful hooks
        self.checkpointer = DetectionCheckpointer(
            # Assume you want to save checkpoints together with logs/statistics
            model,
            cfg.OUTPUT_DIR,
            optimizer=optimizer,
            scheduler=self.scheduler,
        )
        self.cfg = cfg

    @classmethod
    def build_al_dataset(cls, cfg):
        return build_al_dataset(cfg)

    @classmethod
    def build_evaluator(cls, cfg, dataset_name, output_folder=None):
        return COCOEvaluator(dataset_name, cfg, True, output_folder)

    def build_hooks(self):
        cfg = self.cfg.clone()
        cfg.defrost()
        cfg.DATALOADER.NUM_WORKERS = 0  # save some memory and time for PreciseBN

        ret = [
            hooks.IterationTimer(),
            hooks.LRScheduler(self.optimizer, self.scheduler),
            hooks.PreciseBN(
                # Run at the same freq as (but before) evaluation.
                cfg.TEST.EVAL_PERIOD,
                self.model,
                # Build a new data loader to not affect training
                self.build_train_loader(cfg),
                cfg.TEST.PRECISE_BN.NUM_ITER,
            )
            if cfg.TEST.PRECISE_BN.ENABLED and get_bn_modules(self.model)
            else None,
        ]

        if comm.is_main_process():
            ret.append(hooks.PeriodicCheckpointer(self.checkpointer, cfg.SOLVER.CHECKPOINT_PERIOD))

        def test_and_save_results():
            res = self._last_eval_results = self.test(self.cfg, self.model)
            eval_dir = os.path.join(self.cfg.OUTPUT_DIR, 'evals')
            os.makedirs(eval_dir, exist_ok=True)
            pd.DataFrame(res).to_csv(os.path.join(eval_dir, f'{self.round}.csv'))
            return self._last_eval_results
        
        ret.append(hooks.EvalHook(cfg.TEST.EVAL_PERIOD, test_and_save_results))

        if comm.is_main_process():
            # run writers in the end, so that evaluation metrics are written
            ret.append(hooks.PeriodicWriter(self.build_writers(), period=20))
        return ret

    def register_hooks(self, hooks):
        hooks = [h for h in hooks if h is not None]
        for h in hooks:
            assert isinstance(h, HookBase)
            h.trainer = weakref.proxy(self)
        self._hooks = hooks

    def train_al(self):
        """
        Run training for active learning

        Returns:
            OrderedDict of results, if evaluation is enabled. Otherwise None.
        """
        
        logger = logging.getLogger(__name__)
        self.al_dataset.create_initial_dataset()

        logger.info("The estimated total number of iterations is {}".format(self.al_dataset.calculate_estimated_total_iterations()))
        total_round = self.cfg.AL.TRAINING.ROUNDS - 1
        for self.round in range(self.cfg.AL.TRAINING.ROUNDS):
            
            logger.info("Started training for round:{}/{}".format(self.round, total_round))
            # Initialize the dataloader and the training steps 
            dataloader, max_iter = self.al_dataset.get_training_dataloader()
            self._data_loader_iter = iter(dataloader)
            self.start_iter, self.max_iter = 0, max_iter
            
            # Build the hooks for each round
            self.register_hooks(self.build_hooks())

            # Run the main training loop
            self.train()
            
            if self.round != total_round:
                # Run the scoring pass and create the new dataset
                # except for the last round
                self.model.eval()
                logger.info("Started running scoring for round:{}/{}".format(self.round, total_round))
                self.run_scoring_step()
                self.model.train()

    def run_scoring_step(self):
        """
        Run image/object scoring step in active learning 
        And create the new dataset. 
        The implementation is different for image-level 
        and object-level active learning.
        """ 
        pass

class ImageActiveLearningTrainer(ActiveLearningTrainer):

    def run_scoring_step(self):
        """
        For image-level active learning dataset, it will perform
        image-level scoring and update the dataset
        """ 
        
        oracle_dataloader, max_iter = self.al_dataset.get_oracle_dataloader()
        oracle_dataloader_iter = iter(oracle_dataloader)
        
        image_scores = []
        for _iter in range(max_iter):
            data = next(oracle_dataloader_iter)
            image_scores.extend(self.model.generate_image_al_scores(data))

        self.al_dataset.create_new_dataset(image_scores)


class ObjectActiveLearningTrainer(ActiveLearningTrainer):

    def run_scoring_step(self):
        """
        For object-level active learning dataset, it will perform
        object-level scoring and update the dataset
        """ 
        
        oracle_dataloader, max_iter = self.al_dataset.get_oracle_dataloader()
        oracle_dataloader_iter = iter(oracle_dataloader)
        
        fused_results = []
        for _iter in range(max_iter):
            data = next(oracle_dataloader_iter)
            preds = self.model.generate_object_al_scores(data)

            for gt, pred in zip(data, preds):
                fused_results.append(self.object_fusion.combine(pred, gt, self.round))

        self.al_dataset.create_new_dataset(fused_results)