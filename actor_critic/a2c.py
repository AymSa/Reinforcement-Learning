# -*- coding: utf-8 -*-
"""A2C.ipynb

Automatically generated by Colaboratory.

"""
# Commented out IPython magic to ensure Python compatibility.
import numpy as np 
import scipy.signal
import torch 
import torch.nn as nn
from torch.utils.tensorboard import SummaryWriter
import copy
import time
from core import *
from memory import *
from utils import *
from torch.distributions import Categorical
# %load_ext tensorboard
import gridworld
from ac import *

device = torch.device('cuda' if torch.cuda.is_available() else 'cpu') #A UTILISER PLUS TARD

def make_config_gridworld(configName, map = 1,nbEpisodes=100,lam=0.95,stepsEpisode=4000,maxLengthTrain=500,maxLengthTest=500,nbTest=1,freqUpdate=50,freqTest=10,freqVerbose=10):

  text = ["env: gridworld-v0",
          "map: gridworldPlans/plan"+str(map)+".txt",
          "rewards : {0: -0.001, 3: 1, 4: 1, 5: -1, 6: -1}",
          "seed: 5",                                 
          "nbEpisodes: "+str(nbEpisodes),
          "maxLengthTrain : "+str(maxLengthTrain),
          "maxLengthTest : "+str(maxLengthTest),
          "nbTest : "+str(nbTest),
          "freqUpdate : "+str(freqUpdate),
          "freqTest : "+str(freqTest),
          "freqVerbose : "+str(freqVerbose),
          "stepsEpisode : "+str(stepsEpisode),
          "lam : "+str(lam),
          "featExtractor: !!python/name:__main__.MapFromDumpExtractor2 ''  ",                                                                       
          "execute: | ",
          ' env.setPlan(config["map"], config["rewards"])']
  with open(configName,'w') as f:
    
    f.write('\n'.join(text))
  return configName

def make_config(configName,env,nbEpisodes=100,lam=0.95,stepsEpisode=4000,maxLengthTrain=500,maxLengthTest=500,nbTest=1,freqUpdate=50,freqTest=10,freqVerbose=10):

  text = ["env: "+env   ,                                            
          "seed: 5",
          "featExtractor: !!python/name:__main__.NothingToDo ''",
          "nbEpisodes: "+str(nbEpisodes),
          "lam : "+str(lam),
          "maxLengthTrain : "+str(maxLengthTrain),
          "maxLengthTest : "+str(maxLengthTest),
          "nbTest : "+str(nbTest),
          "freqUpdate : "+str(freqUpdate),
          "freqTest : "+str(freqTest),
          "freqVerbose : "+str(freqVerbose),
          "stepsEpisode : "+str(stepsEpisode),
          ]
  with open(configName,'w') as f:
    
    f.write('\n'.join(text))
  return configName



class A2CAgent(nn.Module):
  def __init__(self,env,opt,logger): 
    super(A2CAgent,self).__init__()
    self.opt = opt
    self.env = env
    self.test = False
    self.logger = logger 
    self.featureExtractor = self.opt['featExtractor'](self.env)

    self.n_actions = self.env.action_space.n
    self.obs_size = self.featureExtractor.outSize


    self.z = 0


    
    self.ac = ActorCritic(self.obs_size, self.n_actions).to(device).to(torch.float32)
    self.critic_target = copy.deepcopy(self.ac.critic)
    for p in self.critic_target.parameters(): #on freeze tout les parametres du target qu'on mettera à jour manuellement
        p.requires_grad = False
    

    #Hyperparametres 
    
    self.gamma, self.lam = 0.99, self.opt.lam
    self.actor_lr, self.critic_lr = 0.0003, 0.001

    self.buffer = Memory(self.obs_size,self.n_actions,self.opt.stepsEpisode,self.gamma,self.lam) #a modifier pour prendre en compte le prioritized sampling
    #self.buffer = Memory2(self.opt.stepsEpisode,self.obs_size,self.gamma,self.lam) #self.opt.stepsEpisode
    #BACKWARD 

    self.actor_optimizer = torch.optim.Adam(self.ac.actor.parameters(), lr = self.actor_lr)
    self.critic_optimizer = torch.optim.Adam(self.ac.critic.parameters(), lr = self.critic_lr)

    self.critic_criterion = nn.SmoothL1Loss().to(device)

    self.KLDiv = nn.KLDivLoss(log_target=True, reduction='batchmean')


  def loss_actor(self,obs, actions, advantages,logp_old):
    pi, logp = self.ac.actor(obs, actions)

    kl = self.KLDiv(logp,logp_old)
    self.logger.direct_write("KLDiv",kl,self.z)

    loss = -(logp*advantages).mean()
    return loss

  def loss_critic(self,obs, returns):
    return self.critic_criterion(self.ac.critic(obs),returns).mean()

  def learn(self):
    #obs, actions, returns, advantages= self.sample() # important de l'appeller meme en test pour reinitialiser le buffer
    if not self.test:
      obs, actions, returns, advantages, logp_old = self.sample()

       
      self.actor_optimizer.zero_grad()
      loss_actor = self.loss_actor(obs, actions, advantages,logp_old)
      loss_actor.backward()
      self.actor_optimizer.step()
          
      
     
      self.critic_optimizer.zero_grad()
      loss_critic = self.loss_critic(obs, returns)
      loss_critic.backward()
      self.critic_optimizer.step()

      self.update_target()
      self.z += 1 
      #self.reset_buffer()

    else:
      pass

    

  def store(self,ob, action, reward, value,value_target, logp,done):
    self.buffer.store(ob, action, reward, value, value_target, logp,done)

  def sample(self):
    data = self.buffer.get()
    return data['obs'].to(device), data['act'].to(device), data['ret'].to(device), data['adv'].to(device), data['logp'].to(device)

  def sample2(self):   #TD(0) pour advantage
    _,_,data = self.buffer.sample(self.opt.stepsEpisode)  #retourne un array [tr1,...]
    
    A = [[], [], [], [],[],[]]
    for tr in data:
      for i in range(6):
        A[i].append(tr[i])

    for i in range(len(A)):
      A[i] = torch.vstack(A[i]).to(device)
    
    obs,actions,rewards,vals,vals_targ,dones = A
    
    deltas = rewards + self.gamma * (1-dones) * vals_targ - vals
    advantages = discount_cumsum(deltas,self.gamma * self.lam)
    advantages = torch.from_numpy(advantages.copy()).to(device)
    

    returns = discount_cumsum(rewards,self.gamma)
    returns = torch.from_numpy(returns.copy()).to(device)
    
    return obs, actions, returns, deltas
    
  def finish_path(self,last_val=0):
    self.buffer.finish_path(last_val)

  def reset_buffer(self):
    #self.buffer = Memory2(self.opt.stepsEpisode,self.obs_size,self.gamma,self.lam)
    pass
  
  def update_target(self):
    self.critic_target.load_state_dict(self.ac.critic.state_dict())

outdirs_safe = []

def main(config_file,name,agentClass):
  env, config, outdir, logger = init(config_file,name)
  outdirs_safe.append(outdir)

  freqTest = config["freqTest"]
  freqUpdate = config["freqUpdate"] 
  nbTest = config["nbTest"]
  env.seed(config["seed"])
  np.random.seed(config["seed"])
  episode_count = config["nbEpisodes"]
  maxLengthTrain = config["maxLengthTrain"]
  maxLengthTest = config["maxLengthTest"]
  stepsEpisode = config["stepsEpisode"]



  agent = agentClass(env,config,logger)

  rsum = 0 #somme cumulé pour chaque épisode 
  mean = 0
  verbose = True
  itest = 0
  i=0
  reward = 0
  done = False
  condition_update = False
  forced_done = False


  for episode in range(episode_count):
    checkConfUpdate(outdir,config)

    rsum = 0 #on remet à 0 la somme cumulé à chaque episode
    ob = env.reset() #premiere observation, on commence le jeu 
    
    j = 0 
    if verbose:
      #env.render()
      pass
    
    new_ob = agent.featureExtractor.getFeatures(ob) #on extrait les features de l'observation initial
    new_ob = torch.from_numpy(new_ob).to(device).to(torch.float32)
    condi = False
    for s in range(stepsEpisode):
      if verbose: #on affiche à chaque étape le jeu
        #env.render()
        pass
      
      if condi : 
        if i % int(config["freqVerbose"]) == 0: #on affiche le jeu tout les 10 épisodes
          verbose = True
        else:
          verbose = False

        if i%freqTest==0 and i>=freqTest: #On test l'agent tout les 10 épisodes (2condition car episode=0 au debut)
          print("Test time!\n")
          mean = 0 #moyenne des rsum en phase de test pour voir comment notre agent se débrouille en moyenne
          agent.test = True #on dit à l'agent de passer en test, donc on ne stock plus les transitions et on ne s'entraine plus 

        if i % freqTest == nbTest and i > freqTest: #Fin du test
                print("End of test, mean reward=", mean / nbTest)
                itest += 1
                logger.direct_write("rewardTest", mean / nbTest, itest)
                agent.test = False
        condi = False


      ob = new_ob

      value_target = agent.critic_target(ob)

      action, value, logp = agent.ac.step(ob)

      new_ob, reward, done, _ = env.step(action.item())

      new_ob = agent.featureExtractor.getFeatures(new_ob)
      new_ob = torch.from_numpy(new_ob).to(device).to(torch.float32)

      j+=1
      

      #on regarde si on a atteint la taille max de transitions 1er condition en phase de train, 2eme en phase de test 
      if ((maxLengthTrain > 0) and (not agent.test) and (j == maxLengthTrain)) or ( (agent.test) and (maxLengthTest > 0) and (j == maxLengthTest)):
                done = True #on force la fin de l'episode même si on n'a pas atteint un état final 
                print("forced done!")
                forced_done = True
      
      agent.store(ob, action.item(), reward, value, value_target, logp,done) #on sauvegarde nos transitions uniquement en phase de train , on ajoute le log_probs 
      rsum += reward

    
      
      
      if(done): #si on atteint un etat final ou qu'on met fin a l'épisode
        i+=1
        if(forced_done):
            value = agent.critic_target(new_ob)
        else:
            value = torch.tensor(0)
        agent.finish_path(value) #permet de calculer les returns et rewards

        print(str(i) + " rsum=" + str(rsum) + ", " + str(j) + " actions ")
        logger.direct_write("reward", rsum, i)
        mean += rsum #on sauvegarde le reward cumulé dans une variable qui nous servira à calculer la moyenne
        rsum = 0 #on remet le reward cumulé à 0 pour reprendre un nouveau épisode
        new_ob = agent.featureExtractor.getFeatures(env.reset())
        new_ob = torch.from_numpy(new_ob).to(device).to(torch.float32)
        j = 0

        if((i % int(config["freqVerbose"]) == 0) or (i%freqTest==0 and i>=freqTest) or (i % freqTest == nbTest and i > freqTest)):
          condi = True
        else:
          condi = False
        
        #break
    agent.learn()
  env.close()
  return outdir

def run_env(nbEpisodes=1000):
  outdirs = []
  list_class = [A2CAgent]
  list_name = ["A2CAgent"]
  versions = [0.5] #0 TD(0), TD(lambda), MC
  version_name = ['TD']
  env_name = ["CartPole-v1",
              #"LunarLander-v2"
              ] #
  for agent_class,agent_name in zip(list_class,list_name):
    for versio,version in zip(versions,version_name):
      for env in env_name:
        print("######CHANGEMENT######\n")
        print(agent_name+"_"+str(version)+"_"+env)
        file_config = make_config(agent_name+"_"+str(version)+"_"+env+".yaml",env,nbEpisodes,versio)
        outdir = main(file_config,agent_name+"_"+str(version)+"_"+env,agent_class) 
        outdirs.append(outdir)
  return outdirs

def run_env_gridworld(nbEpisodes=20):
  outdirs = []
  list_class = [ACAgent]
  list_name = ["ACAgent"]
  versions = [0,1] #0 sans target network ni prioritized replay, 1 avec
  maps = [0]

  for map in maps:
    for agent_class,agent_name in zip(list_class,list_name):
      for version in versions:
        print("######CHANGEMENT######")
        print(agent_name+"_"+str(version)+"_"+str(map))
        file_config = make_config_gridworld(agent_name+"_"+str(version)+"_"+str(map)+".yaml",map,nbEpisodes)
        outdir = main(file_config,agent_name+"_"+str(version)+"_"+str(map),agent_class,version)
        outdirs.append(outdir)
  return outdirs

if __name__ == "__main__": #On va mtn faire en sorte que notre algo s'entraine 
    outdirs = run_env(100)
    outdirs

# Commented out IPython magic to ensure Python compatibility.
# %tensorboard --logdir=./XP/CartPole-v1/A2CAgent_TD_CartPole-v1_20-12-2021-12H58-55S

# Commented out IPython magic to ensure Python compatibility.
# %tensorboard --logdir=./XP/CartPole-v1/A2CAgent_MC_CartPole-v1_20-12-2021-11H55-45S

